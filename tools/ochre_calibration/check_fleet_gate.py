"""Gate a simulated fleet against the study's own stated feeder physics.

This exists because the failure it catches is silent. A fleet whose dwellings
are individually plausible can still scale to a feeder two or three times
heavier than the study supports, and nothing about the curves looks wrong --
which is exactly the class of regression CLAUDE.md forbids shipping unnoticed.

Three assertions, every threshold traceable to a source already in the repo:

* **Per-dwelling level.** ``gridalyn/assets/datagen/agents/buildings.py``
  calibrates a Quebec all-electric dwelling at ~6 kW of heat at -25 degC plus
  ~1.5 kW of background, and ~20-22 MWh/yr.
* **Coincidence.** ``projects/ev_hosting_flex/CALIBRATION.md`` records CF ~0.85
  for resistance-heating districts, with a defensible LV diversity factor of
  1.0-1.5. A fleet far below 0.85 has manufactured diversity the physics does
  not support; one at ~1.0 has none.
* **Feeder aggregate.** The same module puts a 3,235-dwelling all-electric
  feeder near 18-19 MW of winter peak.

The gate reports, it does not repair. A breach means either the sample or the
model is wrong, and which one it is takes a human.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Thresholds anchored to MEASUREMENT, not to an assumption.
#
# An earlier version of this gate took its bands from the calibration comments
# in ``gridalyn/assets/datagen/agents/buildings.py`` (~20-22 MWh/yr, ~7.5 kW
# per dwelling, an 18-19 MW feeder) and from the CF ~0.85 that
# ``projects/ev_hosting_flex/CALIBRATION.md`` cites from the literature. Both
# were checked against the measured Hydro-Quebec all-electric subset
# (``datasets/hq``, n=215, 15-minute, year 2018-04-03..2019-04-02) and both are
# wrong for this stock:
#
#   quantity                     buildings.py   MEASURED (HQ)
#   dwelling annual              20-22 MWh      29.4 MWh (p10 16.8, p90 37.3)
#   dwelling peak                ~7.5 kW        18.3 kW (p10 11.7, p90 23.5)
#   coincidence factor           0.85 (lit.)    0.545 at 32 homes, 0.508 at 215
#   pooled peak per home         ~7.5 kW        9.75 kW at 32, 9.09 kW at 215
#
# So the gate now asks whether a fleet resembles the metered stock. The bands
# are the measured median with headroom for the sampling spread; ``datasets/hq``
# is gitignored, so the numbers are transcribed here and this gate stays
# runnable without it.
ANNUAL_MWH = (24.0, 35.0)  # measured median 29.4
DWELLING_PEAK_KW = 9.75  # measured pooled peak per home at 32 dwellings
COINCIDENCE_BAND = (0.47, 0.65)  # measured 0.545 at 32, 0.508 at 215
FEEDER_MW = (25.0, 33.0)  # 3,235 x ~9.0 kW/home from the measured curve
FEEDER_HOMES = 3235
TOLERANCE = 1.35  # how far past a bound is still a warning rather than a breach


def _verdict(value: float, low: float, high: float) -> str:
    """Return pass/warn/fail for a value against a band."""
    if low <= value <= high:
        return "pass"
    span = high * TOLERANCE if value > high else low / TOLERANCE
    return "warn" if (value <= span if value > high else value >= span) else "fail"


def main(argv: list[str] | None = None) -> int:
    """Check a fleet's scaling report and print a verdict per assertion."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", default=".ochre-calibration/fleet")
    args = parser.parse_args(argv)
    workdir = Path(args.workdir).resolve()

    summary = json.loads((workdir / "fleet_summary.json").read_text(encoding="utf-8"))
    scaling = json.loads(
        (workdir / "scaling_validation.json").read_text(encoding="utf-8")
    )

    annual = sorted(summary["annual_kwh"].values())
    median_mwh = annual[len(annual) // 2] / 1000.0
    curve = scaling["coincidence_curve"]
    pooled = curve[-1]
    feeder = [f for f in scaling["feeder_scale_up"] if f["jitter_steps"] == 0][0]

    checks = [
        {
            "check": "dwelling_annual_mwh",
            "value": round(median_mwh, 2),
            "band": list(ANNUAL_MWH),
            "verdict": _verdict(median_mwh, *ANNUAL_MWH),
            "source": "datasets/hq measured median 29.4 MWh (n=215)",
        },
        {
            "check": "pooled_peak_kw_per_home",
            "value": pooled["peak_kw_per_home"],
            "band": [DWELLING_PEAK_KW * 0.7, DWELLING_PEAK_KW * 1.3],
            "verdict": _verdict(
                pooled["peak_kw_per_home"],
                DWELLING_PEAK_KW * 0.7,
                DWELLING_PEAK_KW * 1.3,
            ),
            "source": "datasets/hq measured 9.75 kW/home pooled at 32 dwellings",
        },
        {
            "check": "coincidence_factor",
            "value": pooled["coincidence_factor"],
            "band": list(COINCIDENCE_BAND),
            "verdict": _verdict(pooled["coincidence_factor"], *COINCIDENCE_BAND),
            "source": "datasets/hq measured CF 0.545 at 32 dwellings",
        },
        {
            "check": f"feeder_mw_at_{FEEDER_HOMES}_homes",
            "value": feeder["feeder_peak_mw"],
            "band": list(FEEDER_MW),
            "verdict": _verdict(feeder["feeder_peak_mw"], *FEEDER_MW),
            "source": "datasets/hq measured curve extrapolated to 3,235 homes",
        },
    ]

    worst = "pass"
    for check in checks:
        if check["verdict"] == "fail":
            worst = "fail"
        elif check["verdict"] == "warn" and worst == "pass":
            worst = "warn"

    print(json.dumps({"verdict": worst, "checks": checks}, indent=2))
    if worst == "fail":
        print(
            "fleet does not scale to the study's stated feeder physics; "
            "do not connect it to the network twin",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
