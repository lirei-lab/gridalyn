"""Generate per-building EV charging time series for digital-twin scenarios."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from gridalyn.simulation.simulators.agents.ev import EVCharger


ROOT = Path(__file__).resolve().parents[4]
DEFAULT_BASE_DIR = ROOT / "instances" / "default" / "digital_twin" / "base"
DEFAULT_SCENARIO_DIR = ROOT / "instances" / "default" / "digital_twin" / "scenarios"
DEFAULT_OUT_DIR = ROOT / "instances" / "default" / "digital_twin" / "timeseries"
DEFAULT_CONFIG_PATH = ROOT / "configs" / "grid" / "config.json"
DEFAULT_START = "2024-01-01 00:00:00"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r") as f:
        return json.load(f)


def _relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _scenario_sort_key(scenario_id: str) -> tuple[int, str]:
    match = re.fullmatch(r"S(\d+)", scenario_id)
    if match:
        return int(match.group(1)), scenario_id
    return 10_000, scenario_id


def _profile_seed(assignment_seed: int, pandapower_load: int) -> int:
    return int(assignment_seed + 7919 * (pandapower_load + 1))


def _simulate_one_ev_profile(
    unit_id: int,
    charger_kw: float,
    c_soft_fraction: float,
    seed: int,
    minutes: np.ndarray,
    resolution_minutes: int,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    battery_kwh = float(rng.uniform(40.0, 80.0))
    charger = EVCharger(
        unit_id=unit_id,
        n_evs=1,
        charger_kw=charger_kw,
        c_soft_fraction=c_soft_fraction,
        battery_kwh=battery_kwh,
        rng=rng,
    )
    profile = np.zeros(len(minutes), dtype=np.float32)
    for i, minute in enumerate(minutes):
        profile[i] = float(charger.step(int(minute), dt=resolution_minutes)["p_ev_kw"])
    return profile


def generate_ev_timeseries(
    base_dir: Path,
    scenario_dir: Path,
    out_dir: Path,
    config_path: Path,
    start_timestamp: str,
    resolution_minutes: int | None,
) -> None:
    buildings = pd.read_parquet(base_dir / "buildings.parquet")
    assignments = pd.read_parquet(scenario_dir / "ev_assignments.parquet")
    scenario_index = _load_json(scenario_dir / "index.json")
    config = _load_json(config_path)

    dt_min = int(resolution_minutes or config.get("simulation", {}).get("resolution_minutes", 5))
    steps_per_day = int(24 * 60 / dt_min)
    minutes = np.arange(0, 24 * 60, dt_min, dtype=np.int32)
    if len(minutes) != steps_per_day:
        raise RuntimeError("Unexpected timestamp count for one-day EV simulation.")

    out_dir.mkdir(parents=True, exist_ok=True)

    building_ids = buildings["building_id"].to_numpy()
    load_ids = buildings["load_id"].to_numpy()
    pandapower_loads = buildings["pandapower_load"].astype(np.int64).to_numpy()
    timestamps = pd.date_range(start_timestamp, periods=steps_per_day, freq=f"{dt_min}min").astype(str)

    assignment_seed = int(scenario_index["assignment_seed"])
    scenario_ids = sorted(assignments["scenario_id"].unique(), key=_scenario_sort_key)
    summaries = []

    for scenario_id in scenario_ids:
        scenario_doc = _load_json(scenario_dir / f"{scenario_id}.json")
        scenario_assignments = (
            assignments.loc[assignments["scenario_id"] == scenario_id]
            .sort_values("pandapower_load")
            .reset_index(drop=True)
        )
        ordered_buildings = buildings.sort_values("pandapower_load").reset_index(drop=True)
        if not scenario_assignments["building_id"].equals(ordered_buildings["building_id"]):
            raise RuntimeError(f"{scenario_id}: assignment rows do not align with building order.")

        matrix = np.zeros((steps_per_day, len(ordered_buildings)), dtype=np.float32)
        active = scenario_assignments.loc[scenario_assignments["has_ev"]]
        for _, row in active.iterrows():
            load_idx = int(row["pandapower_load"])
            profile = _simulate_one_ev_profile(
                unit_id=load_idx,
                charger_kw=float(row["charger_kw"]),
                c_soft_fraction=float(row["c_soft_fraction"]),
                seed=_profile_seed(assignment_seed, load_idx),
                minutes=minutes,
                resolution_minutes=dt_min,
            )
            matrix[:, load_idx] = profile

        out = pd.DataFrame(
            {
                "timestamp": np.repeat(timestamps, len(ordered_buildings)),
                "scenario_id": scenario_id,
                "building_id": np.tile(building_ids, steps_per_day),
                "load_id": np.tile(load_ids, steps_per_day),
                "pandapower_load": np.tile(pandapower_loads, steps_per_day),
                "p_ev_kw": matrix.reshape(-1),
            }
        )
        path = out_dir / f"{scenario_id}_ev_load.parquet"
        out.to_parquet(path, index=False)

        total_kw = matrix.sum(axis=1)
        peak_idx = int(np.argmax(total_kw))
        summary = {
            "scenario_id": scenario_id,
            "source_scenario": _relpath(scenario_dir / f"{scenario_id}.json"),
            "path": _relpath(path),
            "n_buildings": int(len(ordered_buildings)),
            "n_ev": int(active["has_ev"].sum()),
            "resolution_minutes": dt_min,
            "n_timestamps": int(steps_per_day),
            "rows": int(len(out)),
            "peak_ev_kw": float(total_kw[peak_idx]),
            "peak_timestamp": str(timestamps[peak_idx]),
            "total_ev_kwh": float(total_kw.sum() * dt_min / 60.0),
            "charger_kw": float(scenario_doc["charger_kw"]),
            "profile_seed_policy": "ev_assignment_seed + 7919 * (pandapower_load + 1)",
            "area_m2_used_for_generation": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        summaries.append(summary)
        print(
            f"{scenario_id}: {summary['n_ev']} EVs | "
            f"peak {summary['peak_ev_kw']:.2f} kW | "
            f"energy {summary['total_ev_kwh']:.2f} kWh"
        )

    with (out_dir / "ev_load_summary.json").open("w") as f:
        json.dump(
            {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "start_timestamp": start_timestamp,
                "resolution_minutes": dt_min,
                "assignment_seed": assignment_seed,
                "area_m2_used_for_generation": False,
                "scenarios": summaries,
            },
            f,
            indent=2,
            sort_keys=True,
        )

    print(f"Generated EV load time series in {out_dir}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate digital-twin EV load time series.")
    parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE_DIR)
    parser.add_argument("--scenario-dir", type=Path, default=DEFAULT_SCENARIO_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--start-timestamp", default=DEFAULT_START)
    parser.add_argument("--resolution-minutes", type=int, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    generate_ev_timeseries(
        base_dir=args.base_dir,
        scenario_dir=args.scenario_dir,
        out_dir=args.out_dir,
        config_path=args.config,
        start_timestamp=args.start_timestamp,
        resolution_minutes=args.resolution_minutes,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
