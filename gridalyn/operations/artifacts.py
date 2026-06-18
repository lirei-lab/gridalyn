"""Canonical materialization helpers for flexibility operation artifacts.

Moved essentially verbatim from ``gridalyn.operations.flexibility.artifacts``.
The governed artifact-run lineage routes through
``gridalyn.operations.runs.build_operation_run`` / ``write_operation_run`` and
the KPI report is materialized exactly as before (D-01 bit-for-bit): the report
fields the regression gate compares are unchanged. Internal builders are sourced
from their canonical concept homes (:mod:`gridalyn.operations.constraints`,
:mod:`gridalyn.operations.contracts`, :mod:`gridalyn.operations.domain`,
:mod:`gridalyn.operations.settlement`).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from gridalyn.foundation import ArtifactLayout
from gridalyn.operations.constraints import build_network_constraint_set
from gridalyn.operations.contracts import build_operation_context
from gridalyn.operations.domain import (
    build_dispatch_instructions,
    build_provider_offers,
    build_settlement_records,
)
from gridalyn.operations.runs import build_operation_run, write_operation_run
from gridalyn.operations.settlement import build_operational_kpi_report


def materialize_flexibility_operation_artifacts(
    *,
    root: Path,
    project_id: str,
    scenario_id: str,
    flexibility_dir: Path | None = None,
    out_dir: Path | None = None,
    report_path: Path | None = None,
    catalog_path: Path | None = None,
    manifest_path: Path | None = None,
) -> dict[str, Path]:
    """Write project-local operational Parquet artifacts and KPI reports."""

    root = root.resolve()
    layout = ArtifactLayout(root)
    flexibility_dir = (flexibility_dir or layout.flexibility).resolve()
    project_output_root = root / "projects" / project_id / "outputs"
    out_dir = (out_dir or (project_output_root / "operations")).resolve()
    report_path = (
        report_path
        or (project_output_root / "reports" / "operational_kpi_report.json")
    ).resolve()
    catalog_path = (catalog_path or (out_dir / "operations_catalog.json")).resolve()

    providers = pd.read_parquet(flexibility_dir / "provider_registry.parquet")
    events = pd.read_parquet(flexibility_dir / "locational_clearing_events.parquet")
    selections = pd.read_parquet(
        flexibility_dir / "locational_clearing_selections.parquet"
    )
    impact_path = flexibility_dir / "network_impact_predictions.parquet"
    impact = pd.read_parquet(impact_path) if impact_path.exists() else pd.DataFrame()

    scenario_events = scenario_frame(events, scenario_id)
    scenario_selections = scenario_frame(selections, scenario_id)
    dt_h = infer_dt_h(scenario_events)
    model_version_id = model_version_id_from_artifacts(root)
    study_run_id = study_run_id_from_manifest(root, project_id, manifest_path)
    clearing_method = clearing_method_from_events(scenario_events)
    context = build_operation_context(
        scenario_id=scenario_id,
        clearing_method=clearing_method,
        dt_h=dt_h,
        requirements=scenario_events,
        providers=providers,
        impact=impact,
        model_version_id=model_version_id,
        study_run_id=study_run_id,
    )
    constraints = build_network_constraint_set(
        scenario_events,
        scenario_id=scenario_id,
        source="locational_clearing_events",
        model_version_id=model_version_id,
        study_run_id=study_run_id,
    )
    offers = build_provider_offers(providers, scenario_id=scenario_id)
    dispatch = build_dispatch_instructions(
        selections=scenario_selections,
        providers=providers,
        context=context,
    )
    settlement = build_settlement_records(dispatch, dt_h=dt_h)
    report = build_operational_kpi_report(
        events=scenario_events,
        dispatch_instructions=dispatch,
        settlement_records=settlement,
        constraints=constraints,
        context=context,
        dt_h=dt_h,
    )
    report = {
        **report,
        "operation_context": context.to_dict(),
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "network_constraints": out_dir / "network_constraints.parquet",
        "flexibility_offers": out_dir / "flexibility_offers.parquet",
        "dispatch_instructions": out_dir / "dispatch_instructions.parquet",
        "settlement_records": out_dir / "settlement_records.parquet",
        "report": report_path,
        "operations_catalog": catalog_path,
        "operation_run": out_dir / "operation_run.json",
    }
    constraints.to_parquet(paths["network_constraints"], index=False)
    offers.to_parquet(paths["flexibility_offers"], index=False)
    dispatch.to_parquet(paths["dispatch_instructions"], index=False)
    settlement.to_parquet(paths["settlement_records"], index=False)

    report = {
        **report,
        "inputs": {
            "provider_registry": relpath(
                flexibility_dir / "provider_registry.parquet",
                root,
            ),
            "locational_clearing_events": relpath(
                flexibility_dir / "locational_clearing_events.parquet",
                root,
            ),
            "locational_clearing_selections": relpath(
                flexibility_dir / "locational_clearing_selections.parquet",
                root,
            ),
            "network_impact_predictions": relpath(impact_path, root)
            if impact_path.exists()
            else None,
        },
        "artifacts": {
            name: relpath(path, root)
            for name, path in paths.items()
            if name not in {"report", "operations_catalog", "operation_run"}
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=json_default))
    catalog = build_operations_catalog(
        root=root,
        project_id=project_id,
        scenario_id=scenario_id,
        report=report,
        paths=paths,
    )
    operation_run = build_operation_run(
        operation_id=context.operation_id,
        operation_type="flexibility_clearing",
        scenario_id=scenario_id,
        network_model_version_id=model_version_id or "",
        study_run_id=study_run_id,
        clearing_method=context.clearing_method,
        status="completed",
        input_artifacts=report["inputs"],
        output_artifacts={
            name: relpath(path, root)
            for name, path in paths.items()
            if name
            in {
                "network_constraints",
                "flexibility_offers",
                "dispatch_instructions",
                "settlement_records",
            }
        },
        kpi_report=relpath(report_path, root),
        validation={"valid": True, "errors": [], "warnings": []},
        metrics=report.get("summary", {}),
        governance={"ontology_profile": context.ontology_profile},
    )
    write_operation_run(paths["operation_run"], operation_run)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps(catalog, indent=2, sort_keys=True, default=json_default))
    return paths


def scenario_frame(frame: pd.DataFrame, scenario_id: str) -> pd.DataFrame:
    """Filter a DataFrame to a scenario when it has a scenario_id column."""

    if "scenario_id" not in frame:
        return frame.copy()
    return frame.loc[frame["scenario_id"].astype(str) == str(scenario_id)].copy()


def infer_dt_h(events: pd.DataFrame) -> float:
    """Infer event interval in hours from timestamped clearing events."""

    if "timestamp" not in events or len(events) < 2:
        return 0.25
    timestamps = pd.to_datetime(events["timestamp"].drop_duplicates()).sort_values()
    if len(timestamps) < 2:
        return 0.25
    dt_h = pd.Series(timestamps).diff().dropna().dt.total_seconds().median() / 3600.0
    return float(dt_h) if pd.notna(dt_h) and dt_h > 0 else 0.25


def clearing_method_from_events(events: pd.DataFrame) -> str:
    """Return the clearing method declared by event artifacts."""

    if "clearing_method" not in events or events.empty:
        return "surrogate"
    values = [str(value) for value in events["clearing_method"].dropna().unique()]
    return values[0] if values else "surrogate"


def model_version_id_from_artifacts(root: Path) -> str | None:
    """Resolve the active model-version identifier from default artifacts."""

    metadata_path = ArtifactLayout(root).base / "metadata.json"
    if not metadata_path.exists():
        return None
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("model_version_id"):
        return metadata["model_version_id"]
    model_version = metadata.get("model_version") or {}
    if model_version.get("id"):
        return model_version["id"]
    if metadata.get("config_hash"):
        return f"model:sha256:{metadata['config_hash']}"
    return None


def study_run_id_from_manifest(
    root: Path,
    project_id: str,
    manifest_path: Path | None = None,
) -> str | None:
    """Resolve the study-run identifier from a project run manifest."""

    path = manifest_path or (
        root
        / "projects"
        / project_id
        / "outputs"
        / "manifests"
        / "project_run_manifest.json"
    )
    if not path.exists():
        return None
    manifest = json.loads(path.read_text(encoding="utf-8"))
    study_run = manifest.get("study_run") or {}
    return study_run.get("run_id")


def scenario_ids(root: Path, active_scenario_id: str) -> list[str]:
    """Return expected scenario ids from the default digital-twin scenario index."""

    index_path = ArtifactLayout(root).scenarios / "index.json"
    if not index_path.exists():
        return [active_scenario_id]
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return [active_scenario_id]
    ids = [
        str(item["scenario_id"])
        for item in index.get("scenarios", [])
        if item.get("scenario_id")
    ]
    if active_scenario_id not in ids:
        ids.append(active_scenario_id)
    return ids or [active_scenario_id]


def build_operations_catalog(
    *,
    root: Path,
    project_id: str,
    scenario_id: str,
    report: dict[str, Any],
    paths: dict[str, Path],
) -> dict[str, Any]:
    """Build a dashboard-facing operations catalog for a scenario."""

    scenarios = {}
    for candidate_id in scenario_ids(root, scenario_id):
        if candidate_id != scenario_id:
            scenarios[candidate_id] = {
                "scenario_id": candidate_id,
                "status": "not_generated",
                "reason": "No operation artifacts generated for this scenario.",
            }
            continue
        operation_context = report.get("operation_context") or {}
        scenarios[candidate_id] = {
            "scenario_id": candidate_id,
            "status": "available",
            "operation_id": operation_context.get("operation_id"),
            "clearing_method": operation_context.get("clearing_method"),
            "ontology_profile": operation_context.get("ontology_profile"),
            "governance": report.get("governance", {}),
            "summary": report.get("summary", {}),
            "artifacts": {
                "networkConstraints": webpath(paths["network_constraints"], root),
                "flexibilityOffers": webpath(paths["flexibility_offers"], root),
                "dispatchInstructions": webpath(paths["dispatch_instructions"], root),
                "settlementRecords": webpath(paths["settlement_records"], root),
            },
            "reports": {
                "operationRun": webpath(paths["operation_run"], root),
                "operationalKpis": webpath(paths["report"], root),
            },
        }
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report_id": "operations_catalog",
        "schema_version": "1.0",
        "project_id": project_id,
        "title": "Flexibility Operations Catalog",
        "available_scenarios": [
            item["scenario_id"]
            for item in scenarios.values()
            if item.get("status") == "available"
        ],
        "expected_scenarios": list(scenarios),
        "scenarios": scenarios,
    }


def relpath(path: Path, root: Path) -> str:
    """Return a root-relative path when possible."""

    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def webpath(path: Path, root: Path) -> str:
    """Return a web-style artifact path."""

    return "/" + relpath(path, root).replace("\\", "/").lstrip("/")


def json_default(value: Any) -> Any:
    """JSON fallback for datetime-like objects."""

    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


__all__ = [
    "build_operations_catalog",
    "clearing_method_from_events",
    "infer_dt_h",
    "json_default",
    "materialize_flexibility_operation_artifacts",
    "model_version_id_from_artifacts",
    "relpath",
    "scenario_frame",
    "scenario_ids",
    "study_run_id_from_manifest",
    "webpath",
]
