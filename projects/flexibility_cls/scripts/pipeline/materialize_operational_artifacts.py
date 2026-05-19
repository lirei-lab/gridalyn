#!/usr/bin/env python3
"""Materialize utility-operation artifacts for the EV capacity project."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.operations.flexibility import (  # noqa: E402
    build_dispatch_instructions,
    build_network_constraint_set,
    build_operational_kpi_report,
    build_operation_context,
    build_provider_offers,
    build_settlement_records,
)
from gridalyn.operations.runs import build_operation_run, write_operation_run  # noqa: E402


DEFAULT_FLEX_DIR = ROOT / "digital_twin" / "flexibility"
DEFAULT_OUT_DIR = ROOT / "projects" / "flexibility_cls" / "outputs" / "operations"
DEFAULT_REPORT_PATH = (
    ROOT
    / "projects"
    / "flexibility_cls"
    / "outputs"
    / "reports"
    / "operational_kpi_report.json"
)
DEFAULT_CATALOG_PATH = (
    ROOT
    / "projects"
    / "flexibility_cls"
    / "outputs"
    / "operations"
    / "operations_catalog.json"
)


def materialize_operational_artifacts(
    *,
    root: Path = ROOT,
    scenario_id: str = "S4",
    flexibility_dir: Path | None = None,
    out_dir: Path | None = None,
    report_path: Path | None = None,
    catalog_path: Path | None = None,
) -> dict[str, Path]:
    """Write project-local operational Parquet artifacts and KPI report."""
    root = root.resolve()
    flexibility_dir = (flexibility_dir or (root / "digital_twin" / "flexibility")).resolve()
    out_dir = (
        out_dir
        or (root / "projects" / "flexibility_cls" / "outputs" / "operations")
    ).resolve()
    report_path = (
        report_path
        or (
            root
            / "projects"
            / "flexibility_cls"
            / "outputs"
            / "reports"
            / "operational_kpi_report.json"
        )
    ).resolve()
    catalog_path = (catalog_path or (out_dir / "operations_catalog.json")).resolve()

    providers = pd.read_parquet(flexibility_dir / "provider_registry.parquet")
    events = pd.read_parquet(flexibility_dir / "locational_clearing_events.parquet")
    selections = pd.read_parquet(flexibility_dir / "locational_clearing_selections.parquet")
    impact_path = flexibility_dir / "network_impact_predictions.parquet"
    impact = pd.read_parquet(impact_path) if impact_path.exists() else pd.DataFrame()

    scenario_events = _scenario_frame(events, scenario_id)
    scenario_selections = _scenario_frame(selections, scenario_id)
    dt_h = _infer_dt_h(scenario_events)
    model_version_id = _model_version_id(root)
    study_run_id = _study_run_id(root)
    clearing_method = _clearing_method(scenario_events)
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
            "provider_registry": _relpath(flexibility_dir / "provider_registry.parquet", root),
            "locational_clearing_events": _relpath(
                flexibility_dir / "locational_clearing_events.parquet",
                root,
            ),
            "locational_clearing_selections": _relpath(
                flexibility_dir / "locational_clearing_selections.parquet",
                root,
            ),
            "network_impact_predictions": _relpath(impact_path, root)
            if impact_path.exists()
            else None,
        },
        "artifacts": {
            name: _relpath(path, root)
            for name, path in paths.items()
            if name not in {"report", "operations_catalog", "operation_run"}
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, default=_json_default))
    catalog = _operations_catalog(
        root=root,
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
            name: _relpath(path, root)
            for name, path in paths.items()
            if name
            in {
                "network_constraints",
                "flexibility_offers",
                "dispatch_instructions",
                "settlement_records",
            }
        },
        kpi_report=_relpath(report_path, root),
        validation={"valid": True, "errors": [], "warnings": []},
        metrics=report.get("summary", {}),
        governance={"ontology_profile": context.ontology_profile},
    )
    write_operation_run(paths["operation_run"], operation_run)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps(catalog, indent=2, sort_keys=True, default=_json_default))
    return paths


def _scenario_frame(frame: pd.DataFrame, scenario_id: str) -> pd.DataFrame:
    if "scenario_id" not in frame:
        return frame.copy()
    return frame.loc[frame["scenario_id"].astype(str) == str(scenario_id)].copy()


def _infer_dt_h(events: pd.DataFrame) -> float:
    if "timestamp" not in events or len(events) < 2:
        return 0.25
    timestamps = pd.to_datetime(events["timestamp"].drop_duplicates()).sort_values()
    if len(timestamps) < 2:
        return 0.25
    dt_h = pd.Series(timestamps).diff().dropna().dt.total_seconds().median() / 3600.0
    return float(dt_h) if pd.notna(dt_h) and dt_h > 0 else 0.25


def _clearing_method(events: pd.DataFrame) -> str:
    if "clearing_method" not in events or events.empty:
        return "surrogate"
    values = [str(value) for value in events["clearing_method"].dropna().unique()]
    return values[0] if values else "surrogate"


def _model_version_id(root: Path) -> str | None:
    metadata_path = root / "digital_twin" / "base" / "metadata.json"
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


def _study_run_id(root: Path) -> str | None:
    manifest_path = (
        root
        / "projects"
        / "flexibility_cls"
        / "outputs"
        / "manifests"
        / "project_run_manifest.json"
    )
    if not manifest_path.exists():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    study_run = manifest.get("study_run") or {}
    return study_run.get("run_id")


def _scenario_ids(root: Path, active_scenario_id: str) -> list[str]:
    index_path = root / "digital_twin" / "scenarios" / "index.json"
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


def _webpath(path: Path, root: Path) -> str:
    return "/" + _relpath(path, root).replace("\\", "/").lstrip("/")


def _operations_catalog(
    *,
    root: Path,
    scenario_id: str,
    report: dict[str, Any],
    paths: dict[str, Path],
) -> dict[str, Any]:
    scenarios = {}
    for candidate_id in _scenario_ids(root, scenario_id):
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
                "networkConstraints": _webpath(paths["network_constraints"], root),
                "flexibilityOffers": _webpath(paths["flexibility_offers"], root),
                "dispatchInstructions": _webpath(paths["dispatch_instructions"], root),
                "settlementRecords": _webpath(paths["settlement_records"], root),
            },
            "reports": {
                "operationRun": _webpath(paths["operation_run"], root),
                "operationalKpis": _webpath(paths["report"], root),
            },
        }
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report_id": "operations_catalog",
        "schema_version": "1.0",
        "project_id": "flexibility_cls",
        "title": "Flexibility Operations Catalog",
        "available_scenarios": [
            item["scenario_id"]
            for item in scenarios.values()
            if item.get("status") == "available"
        ],
        "expected_scenarios": list(scenarios),
        "scenarios": scenarios,
    }


def _relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--scenario-id", default="S4")
    parser.add_argument("--flexibility-dir", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--report-path", type=Path, default=None)
    parser.add_argument("--catalog-path", type=Path, default=None)
    args = parser.parse_args()

    paths = materialize_operational_artifacts(
        root=args.root,
        scenario_id=args.scenario_id,
        flexibility_dir=args.flexibility_dir,
        out_dir=args.out_dir,
        report_path=args.report_path,
        catalog_path=args.catalog_path,
    )
    print(
        json.dumps(
            {name: _relpath(path, args.root) for name, path in paths.items()},
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
