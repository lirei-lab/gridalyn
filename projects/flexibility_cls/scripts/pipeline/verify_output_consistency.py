"""Cross-check EV capacity limitation study JSON and parquet outputs.

This script intentionally validates generated artifacts rather than source
logic. It catches stale JSON files after pipeline changes.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from projects.flexibility_cls.scripts.config import N_BUILDINGS

DATA_DIR = ROOT / "projects" / "flexibility_cls" / "outputs" / "data"
JSON_DIR = ROOT / "projects" / "flexibility_cls" / "outputs" / "json"

SCENARIO_RE = re.compile(r"^S\d+_(\d+)pct$")


def _load_json(name: str) -> dict:
    with open(JSON_DIR / name) as f:
        return json.load(f)


def _scenario_items(summary: dict) -> dict[str, dict]:
    return {key: value for key, value in summary.items() if isinstance(value, dict)}


def _assert_close(errors: list[str], label: str, left: float, right: float, tol: float) -> None:
    if not np.isclose(left, right, atol=tol, rtol=0.0):
        errors.append(f"{label}: {left} != {right} (tol={tol})")


def main() -> int:
    errors: list[str] = []

    ev_summary = _load_json("ev_summary_results.json")
    flex = _load_json("flex_requirements.json")
    pandapower = _load_json("pandapower_validation.json")
    dispatch = pd.read_parquet(DATA_DIR / "market_dispatch_timeseries.parquet")
    temporal = pd.read_parquet(DATA_DIR / "congestion_temporal_bounds.parquet")

    scenarios = _scenario_items(ev_summary)
    pp_scenarios = {item["label"]: item for item in pandapower["scenarios"]}
    if set(scenarios) != set(pp_scenarios):
        errors.append(
            f"Scenario sets differ: ev_summary={sorted(scenarios)} "
            f"pandapower={sorted(pp_scenarios)}"
        )

    for label, values in scenarios.items():
        match = SCENARIO_RE.match(label)
        if not match:
            errors.append(f"Scenario label has unexpected format: {label}")
            continue
        ev_pct = int(match.group(1))
        expected_evs = int(round(N_BUILDINGS * (ev_pct / 100.0)))
        if values["n_ev"] != expected_evs:
            errors.append(f"{label}: n_ev {values['n_ev']} != expected {expected_evs}")

        if label in pp_scenarios:
            _assert_close(
                errors,
                f"{label}: pandapower p_peak_mw vs ev_summary unmanaged_peak_mw",
                float(pp_scenarios[label]["p_peak_mw"]),
                float(values["unmanaged_peak_mw"]),
                1e-9,
            )

    dt_h = float(dispatch["t_hours"].iloc[1] - dispatch["t_hours"].iloc[0])
    _assert_close(
        errors,
        "S4 total_soft_cls_mwh",
        float(scenarios["S4_40pct"]["total_soft_cls_mwh"]),
        float(dispatch["p_soft_cls_mw"].sum() * dt_h),
        1e-9,
    )
    _assert_close(
        errors,
        "S4 total_hard_cls_mwh",
        float(scenarios["S4_40pct"]["total_hard_cls_mwh"]),
        float(dispatch["p_hard_cls_mw"].sum() * dt_h),
        1e-9,
    )
    _assert_close(
        errors,
        "S4 total_rebound_mwh",
        float(scenarios["S4_40pct"]["total_rebound_mwh"]),
        float(dispatch["p_rebound_mw"].sum() * dt_h),
        1e-9,
    )

    _assert_close(
        errors,
        "ev_summary p_limit_dynamic_mw legacy alias",
        float(ev_summary["p_limit_dynamic_mw"]),
        float(ev_summary["dynamic_limit_max_mw"]),
        1e-12,
    )
    _assert_close(
        errors,
        "ev_summary dynamic_limit_max_mw vs dispatch",
        float(ev_summary["dynamic_limit_max_mw"]),
        float(dispatch["p_limit_trace_mw"].max()),
        1e-9,
    )
    _assert_close(
        errors,
        "flex dynamic_limit_max_mw vs temporal",
        float(flex["dynamic_limit_max_mw"]),
        float(temporal["p_limit_trace"].max()),
        1e-9,
    )
    _assert_close(
        errors,
        "flex dynamic_limit_min_mw vs temporal",
        float(flex["dynamic_limit_min_mw"]),
        float(temporal["p_limit_trace"].min()),
        1e-9,
    )
    _assert_close(
        errors,
        "flex p_limit_kw legacy alias",
        float(flex["p_limit_kw"]),
        float(flex["dynamic_limit_at_peak_mw"] * 1000.0),
        1e-9,
    )

    if errors:
        print("[EV_CAPACITY_LIMITATION] Output consistency FAILED")
        for error in errors:
            print(f"  - {error}")
        return 1

    print("[EV_CAPACITY_LIMITATION] Output consistency OK")
    print(f"  scenarios: {', '.join(sorted(scenarios))}")
    print(f"  dynamic limit range: {ev_summary['dynamic_limit_min_mw']:.3f}-{ev_summary['dynamic_limit_max_mw']:.3f} MW")
    print(f"  S4 CLS: soft={scenarios['S4_40pct']['total_soft_cls_mwh']:.3f} MWh, hard={scenarios['S4_40pct']['total_hard_cls_mwh']:.3f} MWh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
