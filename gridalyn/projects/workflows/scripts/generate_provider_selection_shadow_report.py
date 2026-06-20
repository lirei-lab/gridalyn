"""Generate a shadow report for locational provider selection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]

from gridalyn.foundation import ArtifactLayout

DEFAULT_LAYOUT = ArtifactLayout(ROOT)

from gridalyn.operations import (
    build_shadow_report,
    write_shadow_report,
)


DEFAULT_DISPATCH = DEFAULT_LAYOUT.flexibility / "market_dispatch_timeseries.parquet"
DEFAULT_PROVIDERS = DEFAULT_LAYOUT.flexibility / "provider_registry.parquet"
DEFAULT_SENSITIVITY = DEFAULT_LAYOUT.flexibility / "network_sensitivity.parquet"
DEFAULT_TRANSFORMERS = DEFAULT_LAYOUT.base / "grid_transformers.parquet"
DEFAULT_OVERLOAD_REPORT = DEFAULT_LAYOUT.reports / "mv_lv_transformer_overload_report.json"
DEFAULT_OUT = DEFAULT_LAYOUT.flexibility / "provider_selection_shadow_report.json"


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
    group = providers.loc[providers["scenario_id"] == scenario_id]
    if group.empty:
        return []
    return (
        group.groupby("constraint_zone_id")["available_capacity_kw"]
        .sum()
        .sort_values(ascending=False)
        .head(top_n)
        .index.astype(str)
        .tolist()
    )


def generate_shadow_report(
    *,
    dispatch_path: Path,
    provider_path: Path,
    sensitivity_path: Path,
    overload_report_path: Path,
    transformers_path: Path,
    out_path: Path,
    scenario_id: str,
    constraint_ids: list[str] | None = None,
    top_constraints: int = 3,
) -> dict:
    dispatch = pd.read_parquet(dispatch_path)
    providers = pd.read_parquet(provider_path)
    sensitivity = pd.read_parquet(sensitivity_path)

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

    report = build_shadow_report(
        dispatch,
        providers,
        sensitivity,
        scenario_id=scenario_id,
        constraint_ids=selected_constraints,
    )
    report["inputs"] = {
        "dispatch": _relpath(dispatch_path),
        "provider_registry": _relpath(provider_path),
        "network_sensitivity": _relpath(sensitivity_path),
        "overload_report": _relpath(overload_report_path),
        "grid_transformers": _relpath(transformers_path),
    }
    report["artifacts"] = {"report": _relpath(out_path)}
    write_shadow_report(out_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate provider-selection shadow report for a project scenario."
    )
    parser.add_argument("--dispatch-path", type=Path, default=DEFAULT_DISPATCH)
    parser.add_argument("--provider-path", type=Path, default=DEFAULT_PROVIDERS)
    parser.add_argument("--sensitivity-path", type=Path, default=DEFAULT_SENSITIVITY)
    parser.add_argument("--overload-report-path", type=Path, default=DEFAULT_OVERLOAD_REPORT)
    parser.add_argument("--transformers-path", type=Path, default=DEFAULT_TRANSFORMERS)
    parser.add_argument("--out-path", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--scenario-id", default="S4")
    parser.add_argument("--constraint-id", action="append", dest="constraint_ids")
    parser.add_argument("--top-constraints", type=int, default=3)
    args = parser.parse_args()

    report = generate_shadow_report(
        dispatch_path=args.dispatch_path,
        provider_path=args.provider_path,
        sensitivity_path=args.sensitivity_path,
        overload_report_path=args.overload_report_path,
        transformers_path=args.transformers_path,
        out_path=args.out_path,
        scenario_id=args.scenario_id,
        constraint_ids=args.constraint_ids,
        top_constraints=args.top_constraints,
    )
    print(
        "Generated provider-selection shadow report "
        f"for {report['scenario_id']} with {report['n_events']} events "
        f"across {len(report['constraint_ids'])} constraints at {args.out_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
