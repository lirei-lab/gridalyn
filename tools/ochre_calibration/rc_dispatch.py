"""Ask the convex surrogate what a flexibility decision is worth.

This is the other half of the surrogate contract. ``measure_flex_bound.py``
reports what EnergyPlus -- the white-box reference -- actually delivers when a
decision is replayed on real Quebec archetypes. This module reports what the RC
model, the convex mechanism the optimizer decides on, *promises* for the same
decision. The gap between the two is the ``ErrorBound``.

Comparability is the whole point, so three things are held identical to the
EnergyPlus arms rather than merely similar:

* **Weather.** The same CWEC2020 dry-bulb series the fleet's dominant station
  supplied, resampled to the RC's one-minute step.
* **Window.** The same cold week.
* **Decision.** The same pre-heat/curtail trajectory, applied relative to each
  dwelling's own setpoint by shifting ``Building.zone_setpoints`` -- the RC's
  per-zone thermostats stay independent, so the dispatch does not collapse the
  latching diversity that is this model's reason for existing.

The loop mirrors ``gridalyn.assets.datagen.agents.fleet.simulate_buildings``
step for step, including its burn-in, because a re-implementation that drifted
from the reference would measure the drift rather than the decision.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

_EPW = (
    Path.home()
    / ".local/share/OpenStudio-HPXML-v1.9.1/weather"
    / "CAN_QC_Quebec.Intl.AP.717140_CWEC2020.epw"
)


def _echo(message: str) -> None:
    """Print progress to stderr."""
    print(message, file=sys.stderr, flush=True)


def read_epw_drybulb(path: Path, year: int) -> pd.Series:
    """Return the EPW dry-bulb column as an hourly series for ``year``."""
    frame = pd.read_csv(path, skiprows=8, header=None, low_memory=False)
    # EPW columns: 0 year, 1 month, 2 day, 3 hour, 4 minute, 6 dry bulb.
    index = pd.to_datetime(
        {
            "year": year,
            "month": frame[1],
            "day": frame[2],
            "hour": frame[3].astype(int) % 24,
        }
    )
    return pd.Series(frame[6].to_numpy(dtype=float), index=index).sort_index()


def dispatch_offsets(index: pd.DatetimeIndex, decision: dict[str, float]) -> np.ndarray:
    """Return the per-step setpoint offset in degC for a decision."""
    hour = index.hour + index.minute / 60.0
    offset = np.zeros(len(index))
    pre = (hour >= decision["preheat_from"]) & (hour < decision["preheat_to"])
    cut = (hour >= decision["curtail_from"]) & (hour < decision["curtail_to"])
    offset[pre] += decision["preheat_delta_c"]
    offset[cut] -= decision["curtail_delta_c"]
    return offset


def run_arm(
    n_homes: int,
    seed: int,
    temps: pd.Series,
    offsets: np.ndarray | None,
    control: str,
    overrides: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Run the RC fleet, optionally shifting setpoints each step."""
    from gridalyn.assets.datagen.agents import make_buildings
    from gridalyn.assets.datagen.load_profiles import ParametricArxGenerator

    buildings = make_buildings(n_homes, seed=seed)
    if overrides:
        # The study does not run the RC on its library defaults: it overrides
        # thermal resistance and heater capacity per project.yaml. Comparing the
        # surrogate against the reference on defaults would measure a model the
        # study never uses.
        for building in buildings:
            if "r" in overrides:
                building.R = overrides["r"]
            if "p_heat_max" in overrides:
                building.p_heat_max = overrides["p_heat_max"]
    base_setpoints = [b.zone_setpoints.copy() for b in buildings]

    generator = ParametricArxGenerator(random_seed=seed)
    generator.load()
    _, background = generator.generate(temp_out_series=temps, n_houses=n_homes)

    # Burn-in, mirroring simulate_buildings: independent stochastic steady state.
    burn_steps = 6 * 60
    start_minute = temps.index[0].hour * 60 + temps.index[0].minute
    first = float(temps.iloc[0])
    for k in range(burn_steps):
        minute = (start_minute - burn_steps + k) % 1440
        slice_kw = background[k % len(background), :]
        for i, building in enumerate(buildings):
            building.step(
                t_out=first,
                minute_of_day=minute,
                p_bg_kw=slice_kw[i],
                p_cap_kw=None,
                control=control,
            )

    dt_min = (temps.index[1] - temps.index[0]).total_seconds() / 60.0
    rows: dict[int, list[float]] = {b.unit_id: [] for b in buildings}
    for k, (stamp, t_out) in enumerate(temps.items()):
        minute = stamp.hour * 60 + stamp.minute
        slice_kw = background[k, :]
        shift = 0.0 if offsets is None else float(offsets[k])
        for i, building in enumerate(buildings):
            if offsets is not None:
                building.zone_setpoints = base_setpoints[i] + shift
            row = building.step(
                t_out=t_out,
                minute_of_day=minute,
                p_bg_kw=slice_kw[i],
                p_cap_kw=None,
                dt_min=dt_min,
                control=control,
            )
            rows[building.unit_id].append(
                float(row["p_heat_kw"]) + float(row["p_bg_kw"])
            )
    return pd.DataFrame(rows, index=temps.index)


def main(argv: list[str] | None = None) -> int:
    """Run both arms through the RC model and report its promised relief."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--homes", type=int, default=29)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--dispatch", required=True)
    parser.add_argument("--start", default="2007-01-10")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--control", default="hysteresis")
    parser.add_argument("--overrides", default=None, help="JSON {r, p_heat_max}")
    args = parser.parse_args(argv)

    decision = json.loads(args.dispatch)
    hourly = read_epw_drybulb(_EPW, year=int(args.start[:4]))
    start = pd.Timestamp(args.start)
    window = hourly.loc[start : start + pd.Timedelta(days=args.days)]
    temps = window.resample("1min").interpolate()
    _echo(f"weather: {len(temps)} minutes, mean {temps.mean():.1f} degC")

    offsets = dispatch_offsets(temps.index, decision)
    overrides = json.loads(args.overrides) if args.overrides else None
    base = run_arm(args.homes, args.seed, temps, None, args.control, overrides)
    _echo("baseline arm done")
    disp = run_arm(args.homes, args.seed, temps, offsets, args.control, overrides)
    _echo("dispatched arm done")

    base15 = base.resample("15min").mean()
    disp15 = disp.resample("15min").mean()
    hour = base15.index.hour + base15.index.minute / 60.0
    cut = (hour >= decision["curtail_from"]) & (hour < decision["curtail_to"])
    pre = (hour >= decision["preheat_from"]) & (hour < decision["preheat_to"])
    post = (hour >= decision["curtail_to"]) & (
        hour < min(decision["curtail_to"] + 3, 24)
    )
    n = base15.shape[1]
    relief = (base15[cut].sum(axis=1) - disp15[cut].sum(axis=1)) / n
    rebound = (disp15[post].sum(axis=1) - base15[post].sum(axis=1)) / n
    preheat = (disp15[pre].sum(axis=1) - base15[pre].sum(axis=1)) / n

    report: dict[str, Any] = {
        "model": "gridalyn RC (convex surrogate)",
        "control": args.control,
        "overrides": overrides,
        "homes": n,
        "decision": decision,
        "promised": {
            "mean_relief_kw_per_home": round(float(relief.mean()), 3),
            "peak_relief_kw_per_home": round(float(relief.max()), 3),
            "preheat_cost_kw_per_home": round(float(preheat.mean()), 3),
            "rebound_kw_per_home": round(float(rebound.mean()), 3),
        },
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
