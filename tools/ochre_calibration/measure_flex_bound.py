"""Measure what a thermal-flexibility decision actually delivers.

The architecture this serves: the RC building model is the **convex decision
mechanism** -- it is what an optimizer can solve against -- and EnergyPlus with
OS-HPXML is the **white-box reference** the decision is checked on. A decision
that only ever gets evaluated by the model that proposed it has not been
validated at all.

Two EnergyPlus arms differing in exactly one thing, the decision:

``base``
    Each dwelling on its own drawn setpoint and setback schedule.
``disp``
    The same dwellings, same seeds, same weather, with a pre-heat/curtail
    setpoint trajectory laid on top -- expressed relative to each household's
    own setpoint, so the dispatch does not erase the diversity it is measured
    against.

Three quantities come out, and each answers a question a study actually asks:

* **Delivered relief** -- kW shed during the curtail window. This is what the
  optimizer promised and what the feeder sees.
* **Rebound** -- kW above baseline after the window closes. A dispatch that
  moves the peak an hour later has not helped anyone.
* **Comfort drift** -- indoor temperature depression during the window. The
  constraint the household, not the grid, cares about.

The scalar these fold into is the surrogate's ``ErrorBound``: promised relief
minus delivered relief, over dwellings the bound was not fitted on.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

_TEMP_HINTS = ("Temperature: Conditioned Space", "Zone Mean Air Temperature")


def _load(results: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (power kW, indoor temperature degC) frames keyed by dwelling."""
    payload = json.loads(results.read_text(encoding="utf-8"))
    minutes = int(payload["resolution_minutes"])
    power: dict[str, pd.Series] = {}
    temperature: dict[str, pd.Series] = {}
    for record in payload["dwellings"]:
        if record["status"] != "ok":
            continue
        name = Path(record["archetype"]).stem
        frame = pd.read_csv(record["timeseries"], low_memory=False).iloc[1:]
        index = pd.to_datetime(frame[frame.columns[0]])
        uses = [
            c
            for c in frame.columns
            if c.startswith("End Use: Electricity:") and "Fans/Pumps" not in c
        ]
        series = (
            frame[uses].apply(pd.to_numeric, errors="coerce").fillna(0.0).sum(axis=1)
        )
        series.index = index
        power[name] = series / (minutes / 60.0)
        # OS-HPXML writes temperatures in FAHRENHEIT while energy is in kWh, and
        # the unit row is the only place that says so. Treating F as C silently
        # inflates a comfort figure by 1.8x, which is exactly the kind of error
        # that looks plausible on a plot.
        units = pd.read_csv(record["timeseries"], nrows=1, low_memory=False)
        for column in frame.columns:
            if any(hint in column for hint in _TEMP_HINTS):
                temp = pd.to_numeric(frame[column], errors="coerce")
                unit = str(units[column].iloc[0]).strip().upper()
                if unit == "F":
                    temp = (temp - 32.0) * 5.0 / 9.0
                temp.index = index
                temperature[name] = temp
                break
    return pd.DataFrame(power), pd.DataFrame(temperature)


def _window(index: pd.DatetimeIndex, start: float, end: float) -> np.ndarray:
    """Return a mask for an hour-of-day window."""
    hour = index.hour + index.minute / 60.0
    return (hour >= start) & (hour < end)


def main(argv: list[str] | None = None) -> int:
    """Compare the dispatched arm against the baseline and report the bound."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--dispatched", required=True)
    parser.add_argument("--dispatch", required=True, help="the decision, as JSON")
    parser.add_argument("--holdout-fraction", type=float, default=0.5)
    parser.add_argument("--days", type=int, default=7)
    args = parser.parse_args(argv)

    decision = json.loads(args.dispatch)
    base_p, base_t = _load(Path(args.base))
    disp_p, disp_t = _load(Path(args.dispatched))
    shared = [c for c in base_p.columns if c in disp_p.columns]
    base_p, disp_p = base_p[shared], disp_p[shared]

    # Coldest window, chosen on the baseline so the dispatch cannot pick it.
    daily = base_p.mean(axis=1).resample("D").mean()
    end = daily.rolling(args.days).mean().idxmax()
    span = slice(end - pd.Timedelta(days=args.days - 1), end + pd.Timedelta(days=1))
    base_p, disp_p = base_p.loc[span], disp_p.loc[span]

    cut = _window(base_p.index, decision["curtail_from"], decision["curtail_to"])
    has_preheat = "preheat_from" in decision
    pre = (
        _window(base_p.index, decision["preheat_from"], decision["preheat_to"])
        if has_preheat
        else np.zeros(len(base_p.index), dtype=bool)
    )
    post = _window(
        base_p.index, decision["curtail_to"], min(decision["curtail_to"] + 3, 24)
    )

    # Split dwellings: the bound must re-derive on homes it was not fitted on.
    cutoff = int(len(shared) * args.holdout_fraction)
    folds = {"fit": shared[:cutoff], "holdout": shared[cutoff:]}

    report: dict[str, object] = {"decision": decision, "dwellings": len(shared)}
    for fold, names in folds.items():
        if not names:
            continue
        b, d = base_p[names], disp_p[names]
        relief = (b[cut].sum(axis=1) - d[cut].sum(axis=1)) / len(names)
        rebound = (d[post].sum(axis=1) - b[post].sum(axis=1)) / len(names)
        preheat = (d[pre].sum(axis=1) - b[pre].sum(axis=1)) / len(names)
        entry = {
            "dwellings": len(names),
            "mean_relief_kw_per_home": round(float(relief.mean()), 3),
            "peak_relief_kw_per_home": round(float(relief.max()), 3),
            "preheat_cost_kw_per_home": (
                round(float(preheat.mean()), 3) if has_preheat else 0.0
            ),
            "rebound_kw_per_home": round(float(rebound.mean()), 3),
            "net_energy_kwh_per_home": round(
                float((d[names].sum(axis=1) - b[names].sum(axis=1)).sum())
                / len(names)
                / 4.0,
                2,
            ),
        }
        if not base_t.empty and not disp_t.empty:
            cols = [c for c in names if c in base_t.columns and c in disp_t.columns]
            if cols:
                drift = disp_t.loc[span, cols][cut] - base_t.loc[span, cols][cut]
                entry["comfort_drift_c_mean"] = round(float(drift.mean().mean()), 3)
                entry["comfort_drift_c_worst"] = round(float(drift.min().min()), 3)
        report[fold] = entry

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
