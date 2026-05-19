"""
Verify digital-twin EV powerflow smoke outputs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[4]
BASE_DIR = ROOT / "digital_twin" / "base"
TIMESERIES_DIR = ROOT / "digital_twin" / "timeseries"


def _load_json(path: Path) -> dict:
    with path.open("r") as f:
        return json.load(f)


def verify_scenarios(scenarios: list[str], timeseries_dir: Path, base_dir: Path) -> None:
    buses = pd.read_parquet(base_dir / "grid_buses.parquet")
    lines = pd.read_parquet(base_dir / "grid_lines.parquet")
    transformers = pd.read_parquet(base_dir / "grid_transformers.parquet")
    buildings = pd.read_parquet(base_dir / "buildings.parquet")

    previous = None
    print("=== EV Powerflow Verification ===")
    for scenario_id in scenarios:
        summary = _load_json(timeseries_dir / f"{scenario_id}_powerflow_summary.json")
        nodes = pd.read_parquet(timeseries_dir / f"{scenario_id}_powerflow_nodes.parquet")
        line_results = pd.read_parquet(timeseries_dir / f"{scenario_id}_powerflow_lines.parquet")
        trafo_results = pd.read_parquet(timeseries_dir / f"{scenario_id}_powerflow_transformers.parquet")
        power = pd.read_parquet(timeseries_dir / f"{scenario_id}_powerflow_power.parquet")

        n_t = int(summary["n_timestamps"])
        expected = {
            "nodes": n_t * len(buses),
            "lines": n_t * len(lines),
            "transformers": n_t * len(transformers),
            "power": n_t * len(buildings),
        }
        actual = {
            "nodes": len(nodes),
            "lines": len(line_results),
            "transformers": len(trafo_results),
            "power": len(power),
        }
        if actual != expected:
            raise SystemExit(f"ERROR: {scenario_id} row counts mismatch. expected={expected}, actual={actual}")

        timestamp_sets = {
            "nodes": set(nodes["timestamp"].unique()),
            "lines": set(line_results["timestamp"].unique()),
            "transformers": set(trafo_results["timestamp"].unique()),
            "power": set(power["timestamp"].unique()),
        }
        if len({frozenset(v) for v in timestamp_sets.values()}) != 1:
            raise SystemExit(f"ERROR: {scenario_id} timestamp sets are not aligned.")

        if "area_m2" in power.columns:
            raise SystemExit(f"ERROR: {scenario_id} powerflow power output must not contain area_m2.")
        mismatch = (power["p_building_mw"] + power["p_ev_mw"] - power["p_total_mw"]).abs().max()
        if float(mismatch) > 1e-8:
            raise SystemExit(f"ERROR: {scenario_id} violates p_total = p_building + p_ev.")
        if (power["p_ev_mw"] < -1e-12).any():
            raise SystemExit(f"ERROR: {scenario_id} has negative EV load.")

        if scenario_id == "S0":
            if float(power["p_ev_mw"].abs().max()) > 1e-12:
                raise SystemExit("ERROR: S0 must have zero EV load.")
            if abs(float(summary["ev_peak_mw"])) > 1e-12:
                raise SystemExit("ERROR: S0 summary must have zero EV peak.")

        if previous is not None:
            if summary["ev_peak_mw"] + 1e-9 < previous["ev_peak_mw"]:
                raise SystemExit(f"ERROR: {scenario_id} EV peak is not monotonic.")
            if summary["ext_grid_peak_mw"] + 1e-6 < previous["ext_grid_peak_mw"]:
                raise SystemExit(f"ERROR: {scenario_id} ext-grid peak is not monotonic.")
            if summary["v_min_pu"] > previous["v_min_pu"] + 1e-6:
                raise SystemExit(f"ERROR: {scenario_id} minimum voltage unexpectedly improved.")

        previous = summary
        print(
            f"{scenario_id}: ext_peak={summary['ext_grid_peak_mw']:.2f} MW | "
            f"ev_peak={summary['ev_peak_mw']:.2f} MW | "
            f"v_min={summary['v_min_pu']:.4f} | "
            f"line_max={summary['line_max_loading_percent']:.2f}% | "
            f"trafo_max={summary['trafo_max_loading_percent']:.2f}%"
        )

    print("OK: EV powerflow outputs are aligned and satisfy p_total = p_building + p_ev.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify digital-twin EV powerflow outputs.")
    parser.add_argument("--scenarios", nargs="+", default=["S0", "S1"])
    parser.add_argument("--timeseries-dir", type=Path, default=TIMESERIES_DIR)
    parser.add_argument("--base-dir", type=Path, default=BASE_DIR)
    args = parser.parse_args()
    verify_scenarios(args.scenarios, args.timeseries_dir, args.base_dir)


if __name__ == "__main__":
    main()
