"""
Verify deterministic EV adoption overlays for the digital twin.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[4]
BASE_DIR = ROOT / "instances" / "default" / "digital_twin" / "base"
SCENARIO_DIR = ROOT / "instances" / "default" / "digital_twin" / "scenarios"
SCENARIOS = {
    "S0": 0,
    "S1": 10,
    "S2": 20,
    "S3": 30,
    "S4": 40,
}


def _load_json(path: Path) -> dict:
    with path.open("r") as f:
        return json.load(f)


def _expected_count(n_buildings: int, pct: int) -> int:
    return int(round(n_buildings * pct / 100.0))


def main() -> None:
    buildings = pd.read_parquet(BASE_DIR / "buildings.parquet")
    assignments = pd.read_parquet(SCENARIO_DIR / "ev_assignments.parquet")
    n_buildings = len(buildings)

    if "area_m2" in assignments.columns:
        raise SystemExit("ERROR: EV assignment table must not contain area_m2.")

    expected_rows = n_buildings * len(SCENARIOS)
    if len(assignments) != expected_rows:
        raise SystemExit(
            f"ERROR: expected {expected_rows} assignment rows, found {len(assignments)}."
        )

    base_building_ids = set(buildings["building_id"])
    assigned_building_ids = set(assignments["building_id"])
    if assigned_building_ids != base_building_ids:
        raise SystemExit("ERROR: assignment building ids do not match the base twin.")

    selected_sets: dict[str, set[str]] = {}
    print("=== EV Scenario Overlay Verification ===")
    for scenario_id, pct in SCENARIOS.items():
        doc = _load_json(SCENARIO_DIR / f"{scenario_id}.json")
        scenario_rows = assignments.loc[assignments["scenario_id"] == scenario_id]
        if len(scenario_rows) != n_buildings:
            raise SystemExit(f"ERROR: {scenario_id} has {len(scenario_rows)} rows.")

        n_ev = int(scenario_rows["has_ev"].sum())
        expected = _expected_count(n_buildings, pct)
        if n_ev != expected:
            raise SystemExit(f"ERROR: {scenario_id} expected {expected} EVs, found {n_ev}.")
        if int(doc["n_ev"]) != expected:
            raise SystemExit(f"ERROR: {scenario_id}.json n_ev does not match expected count.")
        if doc.get("area_m2_used_for_assignment") is not False:
            raise SystemExit(f"ERROR: {scenario_id}.json must declare area_m2_used_for_assignment=false.")

        ev_rows = scenario_rows.loc[scenario_rows["has_ev"]]
        if ev_rows["ev_id"].isna().any():
            raise SystemExit(f"ERROR: {scenario_id} has selected EV rows without ev_id.")
        if ev_rows["ev_id"].nunique() != n_ev:
            raise SystemExit(f"ERROR: {scenario_id} EV ids are not unique.")
        if (scenario_rows.loc[~scenario_rows["has_ev"], "charger_kw"] != 0.0).any():
            raise SystemExit(f"ERROR: {scenario_id} inactive buildings must have charger_kw=0.")

        selected_sets[scenario_id] = set(ev_rows["building_id"])
        print(f"{scenario_id}: {pct:2d}% -> {n_ev:4d} EVs")

    for earlier, later in zip(["S0", "S1", "S2", "S3"], ["S1", "S2", "S3", "S4"]):
        if not selected_sets[earlier].issubset(selected_sets[later]):
            raise SystemExit(f"ERROR: {earlier} EV set must be nested in {later}.")

    seed = int(_load_json(SCENARIO_DIR / "S1.json")["ev_assignment_seed"])
    expected_permutation = np.random.default_rng(seed).permutation(n_buildings)
    buildings_ordered = buildings.reset_index(drop=True)
    expected_s4 = set(buildings_ordered.iloc[expected_permutation[: _expected_count(n_buildings, 40)]]["building_id"])
    if selected_sets["S4"] != expected_s4:
        raise SystemExit("ERROR: S4 assignment does not match the deterministic seed policy.")

    print("OK: scenario overlays are deterministic, nested, and area-independent.")


if __name__ == "__main__":
    main()
