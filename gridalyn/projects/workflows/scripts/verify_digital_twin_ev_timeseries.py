"""
Verify per-building EV charging time series for digital-twin scenarios.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[4]
BASE_DIR = ROOT / "instances" / "default" / "digital_twin" / "base"
SCENARIO_DIR = ROOT / "instances" / "default" / "digital_twin" / "scenarios"
TIMESERIES_DIR = ROOT / "instances" / "default" / "digital_twin" / "timeseries"


def _load_json(path: Path) -> dict:
    with path.open("r") as f:
        return json.load(f)


def main() -> None:
    buildings = pd.read_parquet(BASE_DIR / "buildings.parquet")
    assignments = pd.read_parquet(SCENARIO_DIR / "ev_assignments.parquet")
    summary = _load_json(TIMESERIES_DIR / "ev_load_summary.json")

    scenario_ids = [item["scenario_id"] for item in summary["scenarios"]]
    n_buildings = len(buildings)
    expected_timestamps = int(24 * 60 / int(summary["resolution_minutes"]))
    expected_rows = n_buildings * expected_timestamps

    previous_total = None
    previous_peak = None
    totals_by_scenario = {}

    print("=== EV Time-Series Verification ===")
    for scenario_id in scenario_ids:
        path = TIMESERIES_DIR / f"{scenario_id}_ev_load.parquet"
        df = pd.read_parquet(path)
        scenario_assignments = assignments.loc[assignments["scenario_id"] == scenario_id]
        active_ids = set(scenario_assignments.loc[scenario_assignments["has_ev"], "building_id"])
        inactive_ids = set(scenario_assignments.loc[~scenario_assignments["has_ev"], "building_id"])

        missing_cols = {
            "timestamp",
            "scenario_id",
            "building_id",
            "load_id",
            "pandapower_load",
            "p_ev_kw",
        } - set(df.columns)
        if missing_cols:
            raise SystemExit(f"ERROR: {scenario_id} missing columns {sorted(missing_cols)}.")
        if "area_m2" in df.columns:
            raise SystemExit(f"ERROR: {scenario_id} EV time series must not contain area_m2.")
        if len(df) != expected_rows:
            raise SystemExit(f"ERROR: {scenario_id} expected {expected_rows} rows, found {len(df)}.")
        if df["timestamp"].nunique() != expected_timestamps:
            raise SystemExit(f"ERROR: {scenario_id} timestamp count mismatch.")
        if set(df["building_id"].unique()) != set(buildings["building_id"]):
            raise SystemExit(f"ERROR: {scenario_id} building ids do not match base twin.")
        if (df["p_ev_kw"] < -1e-9).any():
            raise SystemExit(f"ERROR: {scenario_id} has negative EV load.")

        inactive = df.loc[df["building_id"].isin(inactive_ids), "p_ev_kw"]
        if not np.isclose(float(inactive.abs().max()), 0.0, atol=1e-9):
            raise SystemExit(f"ERROR: {scenario_id} inactive buildings have nonzero EV load.")

        active = df.loc[df["building_id"].isin(active_ids), "p_ev_kw"]
        if active_ids and float(active.max()) <= 0.0:
            raise SystemExit(f"ERROR: {scenario_id} active EV buildings never charge.")

        total_by_time = df.groupby("timestamp", sort=True)["p_ev_kw"].sum()
        total_energy = float(total_by_time.sum() * int(summary["resolution_minutes"]) / 60.0)
        peak = float(total_by_time.max())
        totals_by_scenario[scenario_id] = total_by_time

        if previous_total is not None and (total_by_time.values + 1e-6 < previous_total.values).any():
            raise SystemExit(f"ERROR: aggregate EV load is not pointwise monotonic at {scenario_id}.")
        if previous_peak is not None and peak + 1e-6 < previous_peak:
            raise SystemExit(f"ERROR: peak EV load is not monotonic at {scenario_id}.")

        previous_total = total_by_time
        previous_peak = peak
        print(
            f"{scenario_id}: rows={len(df):7d} | "
            f"active={len(active_ids):4d} | peak={peak:8.2f} kW | energy={total_energy:9.2f} kWh"
        )

    if not np.isclose(float(totals_by_scenario["S0"].max()), 0.0, atol=1e-9):
        raise SystemExit("ERROR: S0 must have zero EV load.")

    print("OK: EV time series are aligned, area-independent, and monotonic across scenarios.")


if __name__ == "__main__":
    main()
