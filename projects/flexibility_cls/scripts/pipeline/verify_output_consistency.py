"""Cross-check EV capacity limitation study JSON and parquet outputs.

This script intentionally validates generated artifacts rather than source
logic. It catches stale JSON files after pipeline changes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.operations.flexibility import validate_cls_output_consistency
from projects.flexibility_cls.scripts.config import N_BUILDINGS

DATA_DIR = ROOT / "projects" / "flexibility_cls" / "outputs" / "data"
JSON_DIR = ROOT / "projects" / "flexibility_cls" / "outputs" / "json"


def _load_json(name: str) -> dict:
    with open(JSON_DIR / name) as f:
        return json.load(f)


def main() -> int:
    ev_summary = _load_json("ev_summary_results.json")
    flex = _load_json("flex_requirements.json")
    pandapower = _load_json("pandapower_validation.json")
    dispatch = pd.read_parquet(DATA_DIR / "market_dispatch_timeseries.parquet")
    temporal = pd.read_parquet(DATA_DIR / "congestion_temporal_bounds.parquet")

    result = validate_cls_output_consistency(
        ev_summary=ev_summary,
        flex_requirements=flex,
        pandapower_validation=pandapower,
        dispatch_timeseries=dispatch,
        temporal_bounds=temporal,
        n_buildings=N_BUILDINGS,
    )

    if not result.valid:
        print("[EV_CAPACITY_LIMITATION] Output consistency FAILED")
        for error in result.errors:
            print(f"  - {error}")
        return 1

    print("[EV_CAPACITY_LIMITATION] Output consistency OK")
    print(f"  scenarios: {', '.join(result.scenario_labels)}")
    print(
        "  dynamic limit range: "
        f"{result.dynamic_limit_min_mw:.3f}-{result.dynamic_limit_max_mw:.3f} MW"
    )
    print(
        f"  S4 CLS: soft={result.s4_soft_cls_mwh:.3f} MWh, "
        f"hard={result.s4_hard_cls_mwh:.3f} MWh"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
