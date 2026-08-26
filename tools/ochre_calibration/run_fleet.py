"""Simulate the sampled Quebec fleet at 15 minutes, per end use.

One dwelling at a time, three steps each:

1. **Retime.** The HOT2000 translation asks for ``<Timestep>60</Timestep>``.
   Diversity and coincidence are resolution-sensitive -- the measured
   Hydro-Quebec comparison this fleet feeds works at 15 minutes -- so the
   timestep is rewritten before anything else runs.
2. **Seed the occupants.** ``BuildResidentialScheduleFile`` is invoked with a
   per-dwelling ``schedules_random_seed``. This is the step that cannot be
   skipped: ``run_simulation.rb --add-stochastic-schedules`` never passes a
   seed, and the measure then falls back to ``random_seed = 1``, so every
   dwelling in the fleet would draw the *same* occupancy realisation and the
   aggregate would be perfectly coincident in its non-thermal load.
3. **Simulate.** ``run_simulation.rb --timestep enduses`` writes a per-end-use
   15-minute series.

Known toolchain defect worked around by the caller: OpenStudio-HPXML v1.9.1
ships ``CAN_QC_La.Grande.Riviere.AP.718270_CWEC.epw`` in latin-1, and its own
Ruby XML writer dies on the accented city name with "invalid byte sequence in
UTF-8". The file must be transcoded to UTF-8 before any dwelling that maps to
that station will run.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

OS_HPXML = Path.home() / ".local/share/OpenStudio-HPXML-v1.9.1"
OPENSTUDIO = Path.home() / ".local/share/OpenStudio-3.9.0/bin/openstudio"
SEED_BASE = 1000


def _echo(message: str) -> None:
    """Print progress to stderr."""
    print(message, file=sys.stderr, flush=True)


def _retime(source: Path, target: Path, minutes: int) -> None:
    """Copy the translated HPXML, rewriting its simulation timestep."""
    text = source.read_text(encoding="utf-8")
    target.write_text(
        text.replace("<Timestep>60</Timestep>", f"<Timestep>{minutes}</Timestep>"),
        encoding="utf-8",
    )


def _cap_heating(target: Path, capacity_kw: float) -> int:
    """Pin the electric heating system's output capacity to the archetype's.

    OS-HPXML documents ``HeatingCapacity`` as optional and **autosized** when
    absent, and 81 of this fleet's 82 electric heating systems arrived without
    it. An autosized system is given whatever capacity holds the setpoint at
    the design condition, so a large leaky dwelling gets 46 kW of baseboards --
    more than any of the 215 metered Quebec dwellings ever draws, whose
    measured maximum is 26.2 kW.

    The archetype already states what is installed (``heating_capacity_kw``,
    median 13.0 kW across this pool). Pinning it restores the ceiling a real
    house has, and with it the behaviour a real house shows in a cold snap:
    falling short of setpoint rather than drawing without limit.

    Capacity is written in Btu/hr, the unit the schema specifies, and inserted
    before ``AnnualHeatingEfficiency`` because HPXML is order-sensitive.

    Args:
        target: The HPXML file to rewrite in place.
        capacity_kw: Installed heating capacity from the archetype manifest.

    Returns:
        How many electric heating systems were pinned.
    """
    import re

    text = target.read_text(encoding="utf-8")
    btu_per_hour = round(capacity_kw * 3412.142, 1)
    pinned = 0

    def fix(match: "re.Match[str]") -> str:
        nonlocal pinned
        block = match.group(0)
        if "<HeatingSystemFuel>electricity<" not in block:
            return block
        if "<HeatingCapacity>" in block:
            return block
        anchor = "<AnnualHeatingEfficiency"
        if anchor not in block:
            return block
        pinned += 1
        return block.replace(
            anchor, f"<HeatingCapacity>{btu_per_hour}</HeatingCapacity>{anchor}", 1
        )

    text = re.sub(r"<HeatingSystem>.*?</HeatingSystem>", fix, text, flags=re.S)
    if pinned:
        target.write_text(text, encoding="utf-8")
    return pinned


def _seed_schedules(work: Path, seed: int) -> bool:
    """Generate a seeded stochastic occupancy schedule, rewriting the HPXML."""
    osw = {
        "run_directory": str(work / "osw_run"),
        "measure_paths": [str(OS_HPXML)],
        "steps": [
            {
                "measure_dir_name": "BuildResidentialScheduleFile",
                "arguments": {
                    "hpxml_path": str(work / "in.xml"),
                    "output_csv_path": str(work / "stochastic.csv"),
                    "hpxml_output_path": str(work / "in.xml"),
                    "schedules_random_seed": seed,
                },
            }
        ],
    }
    path = work / "sched.osw"
    path.write_text(json.dumps(osw, indent=1), encoding="utf-8")
    done = subprocess.run(
        [str(OPENSTUDIO), "run", "-w", str(path), "-m"],
        capture_output=True,
        text=True,
    )
    return done.returncode == 0 and (work / "stochastic.csv").is_file()


def _diversify_setpoints(
    work: Path,
    seed: int,
    minutes: int,
    sigma: float,
    jitter: float,
    depths: list[float],
    dispatch: dict[str, float] | None = None,
) -> bool:
    """Append a per-dwelling ``heating_setpoint`` column to the schedule CSV.

    Without this the fleet has no thermostat diversity at all. Every archetype
    carries the same ERS standard operating condition -- 21 degC day, 18 degC
    night, ``TotalSetbackHoursperWeekHeating`` 56 -- and OpenStudio-HPXML gives
    them all one default setback schedule, so all dwellings recover from
    setback in the same quarter hour. Heating is roughly 85% of this fleet's
    load, so that single shared schedule makes the dominant component
    perfectly coincident and flattens the diversity curve.

    The three drawn quantities mirror what the RC generator in
    ``gridalyn.assets.datagen.agents.buildings`` already varies: a household
    comfort preference around 21 degC (its ``ZONE_SETPOINT_SPREAD_C`` is 1.2),
    a setback depth that is sometimes zero because not every household sets
    back at all, and setback start/end hours that scatter the recovery.

    The column is written in Fahrenheit: ``schedules.rb`` converts detailed
    setpoint columns from F to C and applies the deadband offset itself.
    """
    import numpy as np
    import pandas as pd

    path = work / "stochastic.csv"
    frame = pd.read_csv(path)
    steps = len(frame)
    rng = np.random.default_rng(seed)

    base_c = 21.0 + float(rng.normal(0.0, sigma))
    depth_c = float(rng.choice(depths))
    start_h = 22.0 + float(rng.uniform(-jitter, jitter))
    end_h = 6.0 + float(rng.uniform(-jitter, jitter))

    hour = (np.arange(steps) * (minutes / 60.0)) % 24.0
    at_night = (hour >= start_h) | (hour < end_h)
    celsius = np.where(at_night, base_c - depth_c, base_c)
    if dispatch and "preheat_from" in dispatch:
        # Replay a setpoint-shift decision: pre-heat above the household's
        # own setpoint for a window, then curtail below it during the peak.
        # The decision is expressed in the household's own reference frame, so
        # a dwelling that sets 20 degC is pre-heated to 20 + delta, not to a
        # fleet-wide absolute -- otherwise the dispatch would silently erase
        # the setpoint diversity it is being validated against.
        day = np.floor(np.arange(steps) * (minutes / 60.0) / 24.0)
        pre = (hour >= dispatch["preheat_from"]) & (hour < dispatch["preheat_to"])
        cut = (hour >= dispatch["curtail_from"]) & (hour < dispatch["curtail_to"])
        active = day >= dispatch.get("start_day", 0)
        celsius = celsius + np.where(pre & active, dispatch["preheat_delta_c"], 0.0)
        celsius = celsius - np.where(cut & active, dispatch["curtail_delta_c"], 0.0)
    frame["heating_setpoint"] = np.round(celsius * 9.0 / 5.0 + 32.0, 3)

    if dispatch and dispatch.get("cap_ratio") == 0:
        # FULL curtailment, the one cap the two models express EXACTLY the same
        # way. The RC surrogate takes p_cap_kw=0; EnergyPlus has no power cap
        # for electric resistance baseboards -- hvac_maximum_power_ratio is
        # honoured only for variable-speed heat pumps, and is dropped with a
        # warning otherwise -- so the equivalent is a setpoint floored far below
        # the indoor temperature, which leaves the heater off for the window.
        # Partial caps are NOT representable this way and would need the
        # EnergyPlus runtime API; that limit belongs in the error bound's
        # ``method``, not in a silent approximation.
        cut = (hour >= dispatch["curtail_from"]) & (hour < dispatch["curtail_to"])
        celsius = np.where(cut, 4.0, celsius)
        frame["heating_setpoint"] = np.round(celsius * 9.0 / 5.0 + 32.0, 3)
    elif dispatch and "cap_ratio" in dispatch:
        # Power-cap dispatch, the decision variable the RC surrogate actually
        # exposes (``Building.step(p_cap_kw=...)``). OS-HPXML carries it as
        # ``hvac_maximum_power_ratio``, a fraction of maximum power, so the two
        # models can be driven by ONE decision instead of by a setpoint shift
        # on one side and a cap on the other -- a translation whose error would
        # otherwise land inside the surrogate's error bound.
        cap = (hour >= dispatch["curtail_from"]) & (hour < dispatch["curtail_to"])
        ratio = np.where(cap, float(dispatch["cap_ratio"]), 1.0)
        frame["hvac_maximum_power_ratio"] = np.round(ratio, 4)
    frame.to_csv(path, index=False)

    (work / "setpoint_draw.json").write_text(
        json.dumps(
            {
                "seed": seed,
                "sigma": sigma,
                "jitter_hours": jitter,
                "base_setpoint_c": round(base_c, 3),
                "setback_depth_c": depth_c,
                "setback_start_hour": round(start_h, 2),
                "setback_end_hour": round(end_h, 2),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return True


def _simulate(work: Path) -> Path | None:
    """Run the OS-HPXML workflow and return the timeseries CSV, if produced."""
    subprocess.run(
        [
            str(OPENSTUDIO),
            str(OS_HPXML / "workflow/run_simulation.rb"),
            "-x",
            str(work / "in.xml"),
            "-o",
            str(work / "sim"),
            "--timestep",
            "enduses",
            "--timestep",
            "temperatures",
            "--output-format",
            "csv",
            "-s",
        ],
        capture_output=True,
        text=True,
    )
    series = work / "sim/run/results_timeseries.csv"
    return series if series.is_file() else None


def main(argv: list[str] | None = None) -> int:
    """Simulate every dwelling in the fleet manifest."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", default=".ochre-calibration/fleet")
    parser.add_argument("--minutes", type=int, default=15)
    parser.add_argument(
        "--diversify-setpoints",
        action="store_true",
        help="draw a per-dwelling heating setpoint and setback schedule",
    )
    parser.add_argument("--setpoint-sigma", type=float, default=0.6)
    parser.add_argument("--jitter-hours", type=float, default=1.5)
    parser.add_argument("--setback-depths", default="0,0,1.5,2.5,3.0")
    parser.add_argument("--results-name", default="fleet_results.json")
    parser.add_argument(
        "--cap-heating",
        action="store_true",
        help="pin heating capacity to the archetype instead of autosizing",
    )
    parser.add_argument(
        "--dispatch",
        default=None,
        help=(
            'JSON flexibility decision to replay, e.g. \'{"preheat_from":14,'
            '"preheat_to":16,"preheat_delta_c":1.5,"curtail_from":16,'
            '"curtail_to":19,"curtail_delta_c":2.0}\''
        ),
    )
    args = parser.parse_args(argv)

    # Absolute, always. OpenStudio resolves an OSW's `run_directory` relative
    # to the OSW file itself, so a relative workdir silently produces a doubled
    # path like <work>/<work>/osw_run and the measure dies in boost::filesystem.
    workdir = Path(args.workdir).resolve()
    manifest = json.loads((workdir / "fleet_manifest.json").read_text(encoding="utf-8"))
    results: list[dict[str, Any]] = []

    for record in manifest["dwellings"]:
        name = Path(record["archetype"]).stem
        source = workdir / "hpxml" / name / f"{name}.xml"
        work = workdir / "work" / name
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True, exist_ok=True)
        seed = SEED_BASE + int(record["dwelling"])
        started = time.perf_counter()

        _retime(source, work / "in.xml", args.minutes)
        if args.cap_heating:
            _cap_heating(work / "in.xml", float(record["heating_capacity_kw"]))
        if not _seed_schedules(work, seed):
            _echo(f"  {name}: schedule generation FAILED")
            results.append({**record, "status": "schedule_failed", "seed": seed})
            continue
        if args.diversify_setpoints:
            _diversify_setpoints(
                work,
                seed,
                args.minutes,
                args.setpoint_sigma,
                args.jitter_hours,
                [float(x) for x in args.setback_depths.split(",")],
                json.loads(args.dispatch) if args.dispatch else None,
            )
        series = _simulate(work)
        elapsed = round(time.perf_counter() - started, 1)
        if series is None:
            _echo(f"  {name}: simulation FAILED ({elapsed}s)")
            results.append({**record, "status": "sim_failed", "seed": seed})
            continue
        _echo(f"  {name}: ok ({elapsed}s) seed={seed}")
        results.append(
            {
                **record,
                "status": "ok",
                "seed": seed,
                "timeseries": str(series),
                "seconds": elapsed,
            }
        )

    ok = sum(1 for r in results if r["status"] == "ok")
    out = workdir / args.results_name
    out.write_text(
        json.dumps(
            {
                "resolution_minutes": args.minutes,
                "ok": ok,
                "total": len(results),
                "seed_base": SEED_BASE,
                "dwellings": results,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"results": str(out), "ok": ok, "total": len(results)}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
