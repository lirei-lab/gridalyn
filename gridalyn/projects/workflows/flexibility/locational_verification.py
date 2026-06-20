"""Replay locational clearing selections through pandapower."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from gridalyn.foundation import ArtifactLayout
from gridalyn.operations import (
    apply_locational_selections,
    build_locational_clearing_verification_report,
    write_locational_verification_outputs,
)
from gridalyn.projects.workflows.flexibility.spatial_powerflow_validation import (
    DEFAULT_CACHE_DIR,
    DEFAULT_MARKET_DISPATCH_PATH,
    _load_s4_inputs,
    _powerflow_metrics,
)

ROOT = Path(__file__).resolve().parents[4]

DEFAULT_LAYOUT = ArtifactLayout(ROOT)
DEFAULT_PROVIDERS = DEFAULT_LAYOUT.flexibility / "provider_registry.parquet"
DEFAULT_SELECTIONS = DEFAULT_LAYOUT.flexibility / "locational_clearing_selections.parquet"
DEFAULT_CLEARING_REPORT = DEFAULT_LAYOUT.flexibility / "locational_flexibility_clearing_report.json"
DEFAULT_DISPATCH_OUT = DEFAULT_LAYOUT.flexibility / "locational_clearing_dispatch.parquet"
DEFAULT_REPORT_OUT = DEFAULT_LAYOUT.flexibility / "locational_clearing_verification_report.json"


def _relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def generate_report(
    *,
    provider_path: Path,
    selections_path: Path,
    clearing_report_path: Path,
    dispatch_out: Path,
    report_out: Path,
    scenario_id: str,
    cache_dir: Path,
    market_dispatch_path: Path,
) -> dict:
    """Generate a pandapower verification report for locational clearing."""
    if scenario_id != "S4":
        raise ValueError("Current powerflow verification loader supports scenario_id='S4'")

    providers = pd.read_parquet(provider_path)
    selections = pd.read_parquet(selections_path)
    clearing_report = _load_json(clearing_report_path)

    _buildings, _registry, building_kw, ev_kw, _soft_kw, _hard_kw, _rebound_kw = _load_s4_inputs(
        cache_dir=cache_dir,
        market_dispatch_path=market_dispatch_path,
    )
    dt_h = 5.0 / 60.0
    if building_kw.shape[0] > 1:
        dt_h = 24.0 / float(building_kw.shape[0])

    result = apply_locational_selections(
        building_kw=building_kw,
        ev_kw=ev_kw,
        selections=selections,
        providers=providers,
        dt_h=dt_h,
    )

    unmanaged_p_total_mw = (building_kw + ev_kw) / 1000.0
    locational_p_total_mw = (result["managed_building_kw"] + result["managed_ev_kw"]) / 1000.0
    unmanaged_q_mvar = (building_kw / 1000.0) * 0.1
    locational_q_mvar = (result["managed_building_kw"] / 1000.0) * 0.1

    case_metrics = {
        "unmanaged": _powerflow_metrics(
            "unmanaged",
            unmanaged_p_total_mw,
            unmanaged_q_mvar,
            cache_dir=cache_dir,
        ),
        "locational_clearing": _powerflow_metrics(
            "locational_clearing",
            locational_p_total_mw,
            locational_q_mvar,
            cache_dir=cache_dir,
        ),
    }
    clearing_summary = {
        **result["summary"],
        "rebound_delivered_mwh": 0.0,
    }
    constraint_ids = list(
        clearing_report.get("constraint_ids")
        or sorted(selections["constraint_id"].dropna().astype(str).unique())
    )

    report = build_locational_clearing_verification_report(
        scenario_id=scenario_id,
        clearing_summary=clearing_summary,
        case_metrics=case_metrics,
        constraint_ids=constraint_ids,
    )
    report["inputs"] = {
        "provider_registry": _relpath(provider_path),
        "locational_clearing_selections": _relpath(selections_path),
        "locational_clearing_report": _relpath(clearing_report_path),
        "topology_cache": _relpath(cache_dir),
        "market_dispatch": _relpath(market_dispatch_path),
    }
    outputs = write_locational_verification_outputs(
        dispatch=result["dispatch"],
        report=report,
        dispatch_path=dispatch_out,
        report_path=report_out,
    )
    report["artifacts"] = {
        "dispatch": _relpath(outputs["dispatch"]),
        "report": _relpath(outputs["report"]),
    }
    report_out.write_text(json.dumps(report, indent=2, sort_keys=True))
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-path", type=Path, default=DEFAULT_PROVIDERS)
    parser.add_argument("--selections-path", type=Path, default=DEFAULT_SELECTIONS)
    parser.add_argument("--clearing-report-path", type=Path, default=DEFAULT_CLEARING_REPORT)
    parser.add_argument("--dispatch-out", type=Path, default=DEFAULT_DISPATCH_OUT)
    parser.add_argument("--report-out", type=Path, default=DEFAULT_REPORT_OUT)
    parser.add_argument("--scenario-id", default="S4")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--market-dispatch-path", type=Path, default=DEFAULT_MARKET_DISPATCH_PATH)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = generate_report(
        provider_path=args.provider_path,
        selections_path=args.selections_path,
        clearing_report_path=args.clearing_report_path,
        dispatch_out=args.dispatch_out,
        report_out=args.report_out,
        scenario_id=args.scenario_id,
        cache_dir=args.cache_dir,
        market_dispatch_path=args.market_dispatch_path,
    )
    print(
        json.dumps(
            {
                "scenario_id": report["scenario_id"],
                "constraint_ids": report["constraint_ids"],
                "dispatch": report["dispatch"],
                "comparisons": report["comparisons"],
                "artifacts": report["artifacts"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
