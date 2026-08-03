"""Validate the building generator against the real Hydro-Québec 1000-home set.

The base was calibrated on two AGGREGATE properties -- diurnal shape and
aggregate smoothness -- and both check out. Neither constrains what a SINGLE
dwelling does, and that is where the generator was wrong: the historical
``proportional`` controller glides where a real house steps, so its homes arrive
pre-diversified and the aggregate of a FEW homes comes out too smooth. That
matters because ``ev_hosting_flex`` sizes 6-home pole transformers, where real
diversity is nowhere near complete.

This module pins the diversity curve -- peak kW per home as a function of how
many homes share the transformer -- against the measured curve, plus the cycling
statistics that drive it. It is the check that would have caught the defect.

Comparison population: the all-electric subset of the HQ set (electric heating
>= 60% of annual energy, n=215 of 1000). The full 1000 include 232 dwellings
with almost no electric heating; comparing against those understates the real
peak badly and makes a broken generator look calibrated.

Weather is matched, not assumed: the synthetic window and the HQ window are
selected to the same mean outdoor temperature, because load level tracks it
directly and an unmatched window silently biases every number here.

``datasets/hq`` is gitignored, so these skip in CI and are operator-verified.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_HQ = _REPO_ROOT / "datasets" / "hq"
_SKIP = "datasets/hq is gitignored; provide it locally to run this validation"

pytestmark = pytest.mark.skipif(
    not (_HQ / "consumption.h5").is_file(), reason=_SKIP
)

# A cold week, and the HQ week matched to its mean outdoor temperature.
_SYN_HOURS = 24 * 7
_HQ_WINDOW = ("2019-02-08", "2019-02-14")
_N_HOMES = 60
_SEED = 7
_ALL_ELECTRIC_MIN_FRACTION = 0.6


def _all_electric_winter():
    """Return the HQ all-electric winter window as a (steps, homes) array."""
    import pandas as pd

    cons = pd.read_hdf(_HQ / "consumption.h5") / 1000.0
    heat = pd.read_hdf(_HQ / "heating.h5") / 1000.0
    year = slice("2018-04-03", "2019-04-02")
    fraction = heat.loc[year].sum() / cons.loc[year].sum().replace(0, np.nan)
    all_electric = fraction[fraction >= _ALL_ELECTRIC_MIN_FRACTION].index
    return cons.loc[_HQ_WINDOW[0] : _HQ_WINDOW[1], all_electric].to_numpy()


def _synthetic_homes(control: str):
    """Return per-home 15-min kW for the study's base under ``control``."""
    import pandas as pd

    sys.path.insert(0, str(_REPO_ROOT / "projects" / "ev_hosting_flex" / "scripts"))
    from config import BG_SCALE, DHW_SEED_SALT, P_HEAT_QUEBEC, R_STUDY_B

    import _annual
    from gridalyn.assets.datagen.agents import make_buildings, simulate_buildings
    from gridalyn.assets.datagen.agents.dhw import make_dhw_tank_fleet

    hourly = _annual.load_annual_tmy().iloc[:_SYN_HOURS]
    minutely = hourly.resample("1min").interpolate()

    buildings = make_buildings(_N_HOMES, seed=_SEED)
    for building in buildings:
        building.R = R_STUDY_B
        building.p_heat_max = P_HEAT_QUEBEC
    results = simulate_buildings(
        buildings, minutely, burnin_hours=6, random_seed=_SEED, control=control
    )
    envelope = pd.DataFrame(
        {
            uid: (
                results[uid]["p_heat_kw"]
                + results[uid]["p_cool_kw"]
                + BG_SCALE * results[uid]["p_bg_kw"]
            )
            .resample("15min")
            .mean()
            for uid in results
        }
    )
    dhw = np.column_stack(
        [
            make_dhw_tank_fleet(
                np.random.default_rng(_SEED + DHW_SEED_SALT + 1000 * i),
                1,
                hourly,
                res_minutes=15,
            )
            for i in range(_N_HOMES)
        ]
    )
    steps = min(len(envelope), len(dhw))
    return envelope.iloc[:steps].to_numpy() + dhw[:steps]


def _peak_per_home(homes: np.ndarray, group: int, draws: int = 40) -> float:
    """Mean peak kW per home for random groups of ``group`` dwellings."""
    rng = np.random.default_rng(1)
    return float(
        np.mean(
            [
                homes[:, rng.choice(homes.shape[1], group, replace=False)]
                .sum(axis=1)
                .max()
                / group
                for _ in range(draws)
            ]
        )
    )


def test_windows_are_temperature_matched() -> None:
    """The synthetic and HQ windows sit at the same mean outdoor temperature.

    Every other assertion here compares load levels, and load level follows
    ambient directly, so an unmatched pair of windows would bias all of them.
    """
    import pandas as pd

    sys.path.insert(0, str(_REPO_ROOT / "projects" / "ev_hosting_flex" / "scripts"))
    import _annual

    synthetic_mean = float(_annual.load_annual_tmy().iloc[:_SYN_HOURS].mean())
    meteo = pd.read_hdf(_HQ / "meteo.h5")
    hq_mean = float(meteo.loc[_HQ_WINDOW[0] : _HQ_WINDOW[1], "DryBulb"].mean())

    assert abs(synthetic_mean - hq_mean) < 1.0, (
        f"windows are not temperature-matched: synthetic {synthetic_mean:.1f} °C "
        f"vs HQ {hq_mean:.1f} °C. Re-select _HQ_WINDOW before trusting any "
        "comparison in this module."
    )


def test_hysteresis_reproduces_measured_heating_cycling() -> None:
    """Per-zone thermostats cycle like the measured dwellings; gliding does not.

    Real all-electric heating moves more than 2 kW between consecutive 15-min
    samples in ~40% of intervals (mean |Δ| ≈ 2.6 kW). The proportional law
    produces ~0%, which is the mechanism behind the diversity defect.
    """
    sys.path.insert(0, str(_REPO_ROOT / "projects" / "ev_hosting_flex" / "scripts"))
    from config import P_HEAT_QUEBEC, R_STUDY_B

    import _annual
    from gridalyn.assets.datagen.agents import make_buildings, simulate_buildings

    minutely = (
        _annual.load_annual_tmy().iloc[:_SYN_HOURS].resample("1min").interpolate()
    )
    buildings = make_buildings(_N_HOMES, seed=_SEED)
    for building in buildings:
        building.R = R_STUDY_B
        building.p_heat_max = P_HEAT_QUEBEC
    results = simulate_buildings(
        buildings, minutely, burnin_hours=6, random_seed=_SEED, control="hysteresis"
    )
    heat = np.column_stack(
        [
            results[uid]["p_heat_kw"].resample("15min").mean().to_numpy()
            for uid in results
        ]
    )
    steps = np.abs(np.diff(heat, axis=0))

    assert steps.mean() > 1.5, (
        f"heating steps average {steps.mean():.2f} kW; the measured all-electric "
        "dwellings average 2.60 kW. The zones have stopped latching — check that "
        "each thermostat senses its OWN zone_T and not the house mean T_in, which "
        "collapses the ensemble back into a slow proportional law."
    )
    assert np.mean(steps > 2.0) > 0.25, (
        f"only {np.mean(steps > 2.0):.1%} of 15-min intervals move >2 kW; the "
        "measured dwellings do so in 39.9%."
    )


@pytest.mark.parametrize("group", [1, 2, 6, 12])
def test_diversity_curve_tracks_hq(group: int) -> None:
    """Peak per home matches the measured curve from 1 dwelling up to 12.

    The curve, not any single point, is the property that matters: a generator
    whose homes are individually too smooth still matches at large N while
    overstating headroom on a 6-home pole transformer, which is exactly the
    asset ``ev_hosting_flex`` sizes.
    """
    real = _peak_per_home(_all_electric_winter(), group)
    synthetic = _peak_per_home(_synthetic_homes("hysteresis"), group)
    bias = synthetic / real - 1.0

    assert abs(bias) < 0.12, (
        f"peak per home at {group} dwelling(s) is {synthetic:.2f} kW against a "
        f"measured {real:.2f} kW ({bias:+.1%}). Tolerance is ±12%. A NEGATIVE "
        "bias overstates transformer headroom and inflates EV hosting capacity."
    )


def test_hysteresis_is_energy_neutral_against_the_proportional_base() -> None:
    """Switching controllers changes dynamics, not consumption.

    This is what lets the controller change without re-opening the energy
    calibration: the annual-energy anchor (~29 MWh/home, against 28.3 measured
    for the all-electric subset) is untouched by the swap.
    """
    proportional = _synthetic_homes("proportional").mean()
    hysteresis = _synthetic_homes("hysteresis").mean()
    drift = hysteresis / proportional - 1.0

    assert abs(drift) < 0.03, (
        f"mean demand moved {drift:+.2%} between controllers "
        f"({proportional:.3f} -> {hysteresis:.3f} kW/home). The swap is supposed "
        "to redistribute the same energy in time; a drift this large means the "
        "energy calibration (R_STUDY_B) has to be revisited alongside it."
    )
