#!/usr/bin/env python3
"""Generate locational flexibility clearing artifacts from digital-twin providers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from gridalyn.foundation import (
    ArtifactLayout,
    ReportMetadata,
    file_reference,
    write_report,
)
from gridalyn.operations import (
    build_constraint_requirements,
    build_locational_clearing,
    write_locational_clearing_outputs,
)

# Current-directory default, matching ArtifactLayout's own root default. Never
# derive the root from __file__: in an installed wheel that resolves to
# site-packages, where reads return {} and writes land inside the package.
_DEFAULT_ROOT = Path(".")


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


def _constraints_from_overload_report(
    *,
    overload_report_path: Path,
    transformers_path: Path,
    scenario_id: str,
    top_n: int,
) -> list[str]:
    if not overload_report_path.exists() or not transformers_path.exists():
        return []
    report = json.loads(overload_report_path.read_text())
    scenario = next(
        (
            item
            for item in report.get("scenarios", [])
            if str(item.get("scenario_id")) == scenario_id
        ),
        None,
    )
    if not scenario:
        return []
    transformers = pd.read_parquet(transformers_path)
    by_idx = {
        int(row["pandapower_trafo"]): str(row["transformer_id"])
        for row in transformers.to_dict("records")
    }
    constraint_ids = []
    for item in scenario.get("top_transformers", [])[:top_n]:
        trafo_idx = item.get("trafo_idx")
        if trafo_idx is None:
            continue
        constraint_id = by_idx.get(int(trafo_idx))
        if constraint_id:
            constraint_ids.append(constraint_id)
    return constraint_ids


def _fallback_constraints(
    providers: pd.DataFrame, scenario_id: str, top_n: int
) -> list[str]:
    scenario_providers = providers.loc[
        providers["scenario_id"].astype(str) == scenario_id
    ]
    if scenario_providers.empty:
        return []
    return (
        scenario_providers.groupby("constraint_zone_id")["available_capacity_kw"]
        .sum()
        .sort_values(ascending=False)
        .head(top_n)
        .index.astype(str)
        .tolist()
    )


def _infer_dt_h(transformer_timeseries: pd.DataFrame) -> float:
    timestamps = pd.to_datetime(
        transformer_timeseries["timestamp"].drop_duplicates()
    ).sort_values()
    if len(timestamps) < 2:
        return 5.0 / 60.0
    diffs = pd.Series(timestamps).diff().dropna().dt.total_seconds() / 3600.0
    if diffs.empty:
        return 5.0 / 60.0
    return float(diffs.median())


def generate_locational_clearing(
    *,
    root: Path,
    provider_path: Path,
    impact_path: Path,
    overload_report_path: Path,
    transformers_path: Path,
    transformer_timeseries_path: Path,
    out_dir: Path,
    report_path: Path,
    scenario_id: str,
    clearing_method: str,
    constraint_ids: list[str] | None = None,
    top_constraints: int = 3,
) -> dict[str, Any]:
    """Run locational clearing and write its artifacts plus governed report.

    Args:
        root: Workspace root containing ``instances/default/digital_twin``;
            paths in the report are recorded relative to it.
        provider_path: Provider registry parquet.
        impact_path: Network-impact predictions parquet.
        overload_report_path: Transformer overload report JSON (optional on
            disk; constraints fall back to provider capacity ranking).
        transformers_path: Grid transformers parquet.
        transformer_timeseries_path: Scenario transformer loading parquet.
        out_dir: Directory for the events/selections parquets and the flat
            clearing summary sidecar.
        report_path: Destination for the governed clearing report.
        scenario_id: Scenario to clear.
        clearing_method: ``"surrogate"`` or ``"topology"``.
        constraint_ids: Explicit constraint ids; derived when omitted.
        top_constraints: Number of constraints to derive when not explicit.

    Returns:
        The governed report payload written to ``report_path``.

    Raises:
        FileNotFoundError: If ``root`` holds no digital-twin artifact tree —
            the guard that keeps an installed package from reading empty
            inputs and writing artifacts outside a workspace.
        ValueError: If no constraint can be derived for ``scenario_id``.
    """
    root = root.resolve()
    layout = ArtifactLayout(root)
    if not layout.digital_twin.is_dir():
        raise FileNotFoundError(
            f"{layout.digital_twin}: no digital-twin artifact tree under root "
            f"{root}; clearing artifacts would be built from empty inputs and "
            "written outside a workspace. Run from a workspace root containing "
            "instances/default/digital_twin, or pass root=<workspace> "
            "(--root on the command line)."
        )

    providers = pd.read_parquet(provider_path)
    impact = pd.read_parquet(impact_path)
    transformers = pd.read_parquet(transformers_path)
    transformer_timeseries = pd.read_parquet(transformer_timeseries_path)

    selected_constraints = constraint_ids or _constraints_from_overload_report(
        overload_report_path=overload_report_path,
        transformers_path=transformers_path,
        scenario_id=scenario_id,
        top_n=top_constraints,
    )
    if not selected_constraints:
        selected_constraints = _fallback_constraints(
            providers, scenario_id, top_constraints
        )
    if not selected_constraints:
        raise ValueError(f"No constraints available for scenario {scenario_id}")

    transformer_id_by_idx = {
        int(row["pandapower_trafo"]): str(row["transformer_id"])
        for row in transformers.to_dict("records")
    }
    requirements = build_constraint_requirements(
        transformer_timeseries=transformer_timeseries,
        transformer_id_by_idx=transformer_id_by_idx,
        constraint_ids=selected_constraints,
        limit_percent=100.0,
    )
    dt_h = _infer_dt_h(transformer_timeseries)
    events, selections, report = build_locational_clearing(
        requirements=requirements,
        providers=providers,
        impact=impact,
        scenario_id=scenario_id,
        dt_h=dt_h,
        clearing_method=clearing_method,
    )
    # The sidecar keeps the flat legacy shape (report-contract audit §5.5):
    # it has its own consumers and is NOT the run's report.
    sidecar_report = {
        **report,
        "constraint_ids": selected_constraints,
        "inputs": {
            "provider_registry": _relative(provider_path, root),
            "impact": _relative(impact_path, root),
            "overload_report": _relative(overload_report_path, root),
            "grid_transformers": _relative(transformers_path, root),
            "transformer_timeseries": _relative(transformer_timeseries_path, root),
        },
    }
    artifact_paths = write_locational_clearing_outputs(
        out_dir=out_dir,
        events=events,
        selections=selections,
        report=sidecar_report,
    )

    return write_report(
        report_path,
        metadata=ReportMetadata(
            report_id="locational_flexibility_clearing",
            source_domain="operations",
        ),
        inputs=[
            file_reference(path, root)
            for path in (
                provider_path,
                impact_path,
                overload_report_path,
                transformers_path,
                transformer_timeseries_path,
            )
        ],
        artifacts=[
            file_reference(artifact_paths[key], root)
            for key in ("events", "selections", "report")
        ],
        summary={
            "scenario_id": report["scenario_id"],
            "clearing_method": report["clearing_method"],
            "clearing_policy": report["clearing_policy"],
            "dt_h": report["dt_h"],
            "constraint_ids": selected_constraints,
            "clearing_summary": report["summary"],
            "constraint_summary": report["constraint_summary"],
        },
        validation={"valid": True, "errors": [], "warnings": []},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=_DEFAULT_ROOT,
        help=(
            "Workspace root containing instances/default/digital_twin "
            "(default: current directory)."
        ),
    )
    parser.add_argument("--provider-path", type=Path, default=None)
    parser.add_argument("--impact-path", type=Path, default=None)
    parser.add_argument("--overload-report-path", type=Path, default=None)
    parser.add_argument("--transformers-path", type=Path, default=None)
    parser.add_argument("--transformer-timeseries-path", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--report-path", type=Path, default=None)
    parser.add_argument("--scenario-id", default="S4")
    parser.add_argument(
        "--clearing-method", choices=["surrogate", "topology"], default="surrogate"
    )
    parser.add_argument("--constraint-id", action="append", dest="constraint_ids")
    parser.add_argument("--top-constraints", type=int, default=3)
    args = parser.parse_args()

    layout = ArtifactLayout(args.root.resolve())
    flexibility = layout.flexibility
    report = generate_locational_clearing(
        root=args.root,
        provider_path=args.provider_path or flexibility / "provider_registry.parquet",
        impact_path=args.impact_path
        or flexibility / "network_impact_predictions.parquet",
        overload_report_path=args.overload_report_path
        or layout.reports / "mv_lv_transformer_overload_report.json",
        transformers_path=args.transformers_path
        or layout.base / "grid_transformers.parquet",
        transformer_timeseries_path=args.transformer_timeseries_path
        or layout.timeseries / "S4_powerflow_transformers.parquet",
        out_dir=args.out_dir or flexibility,
        report_path=args.report_path
        or flexibility / "locational_flexibility_clearing_report.json",
        scenario_id=args.scenario_id,
        clearing_method=args.clearing_method,
        constraint_ids=args.constraint_ids,
        top_constraints=args.top_constraints,
    )
    print(
        json.dumps(
            {
                "scenario_id": report["summary"]["scenario_id"],
                "clearing_method": report["summary"]["clearing_method"],
                "constraint_ids": report["summary"]["constraint_ids"],
                "summary": report["summary"]["clearing_summary"],
                "artifacts": report["artifacts"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
