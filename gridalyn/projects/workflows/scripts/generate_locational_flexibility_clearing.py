#!/usr/bin/env python3
"""Generate locational flexibility clearing artifacts from digital-twin providers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from gridalyn.foundation import ArtifactLayout
from gridalyn.operations import (
    build_constraint_requirements,
    build_locational_clearing,
    write_locational_clearing_outputs,
)

ROOT = Path(__file__).resolve().parents[4]

DEFAULT_LAYOUT = ArtifactLayout(ROOT)

DEFAULT_PROVIDERS = DEFAULT_LAYOUT.flexibility / "provider_registry.parquet"
DEFAULT_IMPACT = DEFAULT_LAYOUT.flexibility / "network_impact_predictions.parquet"
DEFAULT_TRANSFORMERS = DEFAULT_LAYOUT.base / "grid_transformers.parquet"
DEFAULT_OVERLOAD_REPORT = DEFAULT_LAYOUT.reports / "mv_lv_transformer_overload_report.json"
DEFAULT_TRANSFORMER_TIMESERIES = DEFAULT_LAYOUT.timeseries / "S4_powerflow_transformers.parquet"
DEFAULT_OUT_DIR = DEFAULT_LAYOUT.flexibility
DEFAULT_REPORT_PATH = DEFAULT_LAYOUT.flexibility / "locational_flexibility_clearing_report.json"


def _relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
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


def _fallback_constraints(providers: pd.DataFrame, scenario_id: str, top_n: int) -> list[str]:
    scenario_providers = providers.loc[providers["scenario_id"].astype(str) == scenario_id]
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
    timestamps = pd.to_datetime(transformer_timeseries["timestamp"].drop_duplicates()).sort_values()
    if len(timestamps) < 2:
        return 5.0 / 60.0
    diffs = pd.Series(timestamps).diff().dropna().dt.total_seconds() / 3600.0
    if diffs.empty:
        return 5.0 / 60.0
    return float(diffs.median())


def generate_locational_clearing(
    *,
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
) -> dict:
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
        selected_constraints = _fallback_constraints(providers, scenario_id, top_constraints)
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
    report = {
        **report,
        "constraint_ids": selected_constraints,
        "inputs": {
            "provider_registry": _relpath(provider_path),
            "impact": _relpath(impact_path),
            "overload_report": _relpath(overload_report_path),
            "grid_transformers": _relpath(transformers_path),
            "transformer_timeseries": _relpath(transformer_timeseries_path),
        },
    }
    artifact_paths = write_locational_clearing_outputs(
        out_dir=out_dir,
        events=events,
        selections=selections,
        report=report,
    )

    report = {
        **report,
        "artifacts": {
            "events": _relpath(artifact_paths["events"]),
            "selections": _relpath(artifact_paths["selections"]),
            "summary": _relpath(artifact_paths["report"]),
            "report": _relpath(report_path),
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-path", type=Path, default=DEFAULT_PROVIDERS)
    parser.add_argument("--impact-path", type=Path, default=DEFAULT_IMPACT)
    parser.add_argument("--overload-report-path", type=Path, default=DEFAULT_OVERLOAD_REPORT)
    parser.add_argument("--transformers-path", type=Path, default=DEFAULT_TRANSFORMERS)
    parser.add_argument("--transformer-timeseries-path", type=Path, default=DEFAULT_TRANSFORMER_TIMESERIES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--scenario-id", default="S4")
    parser.add_argument("--clearing-method", choices=["surrogate", "topology"], default="surrogate")
    parser.add_argument("--constraint-id", action="append", dest="constraint_ids")
    parser.add_argument("--top-constraints", type=int, default=3)
    args = parser.parse_args()

    report = generate_locational_clearing(
        provider_path=args.provider_path,
        impact_path=args.impact_path,
        overload_report_path=args.overload_report_path,
        transformers_path=args.transformers_path,
        transformer_timeseries_path=args.transformer_timeseries_path,
        out_dir=args.out_dir,
        report_path=args.report_path,
        scenario_id=args.scenario_id,
        clearing_method=args.clearing_method,
        constraint_ids=args.constraint_ids,
        top_constraints=args.top_constraints,
    )
    print(
        json.dumps(
            {
                "scenario_id": report["scenario_id"],
                "clearing_method": report["clearing_method"],
                "constraint_ids": report["constraint_ids"],
                "summary": report["summary"],
                "artifacts": report["artifacts"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
