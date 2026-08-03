"""Tests for the SDK cold-coupled EV fleet generator."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from gridalyn.assets.datagen.agents import make_cold_coupled_ev_fleet


def _series(hours: int, temp_c: float, start: str = "2020-01-01 00:00") -> pd.Series:
    """Return a flat hourly outdoor-temperature series."""
    idx = pd.date_range(start, periods=hours, freq="h")
    return pd.Series(np.full(hours, float(temp_c)), index=idx)


def test_charges_in_a_block_at_rated_power():
    """The uncontrolled profile must reach the charger's RATED power.

    Guards the anti-circularity fix: the previous SDK session model spread each
    session over the plugged window (``p_needed = energy / t_remain``), so the
    peak flexibility is meant to shave was already flattened by the generator.
    """
    fleet = make_cold_coupled_ev_fleet(
        np.random.default_rng(0),
        n_evs=20,
        temp_series=_series(48, 0.0),
        res_minutes=5,
        charger_mix={7.2: 1.0},
        plugin_base=1.0,
        plugin_kcold=0.0,
        session_kwh_kcold=0.0,
    )
    assert fleet.max() == pytest.approx(7.2, rel=1e-9)


def test_energy_per_session_matches_the_lognormal_mean():
    """Exact minute-overlap allocation must conserve session energy."""
    res = 5
    fleet = make_cold_coupled_ev_fleet(
        np.random.default_rng(1),
        n_evs=400,
        temp_series=_series(48, 20.0),  # mild: cold intensity is 0
        res_minutes=res,
        charger_mix={7.2: 1.0},
        plugin_base=1.0,
        plugin_kcold=0.0,
        session_kwh_kcold=0.0,
    )
    # Two calendar days, one session each, lognormal(median=8, sigma=0.5)
    # -> mean per session = 8 * exp(0.5**2 / 2) = 9.07 kWh.
    kwh_per_ev = fleet.sum(axis=1) * res / 60.0
    assert kwh_per_ev.mean() == pytest.approx(2 * 9.07, rel=0.10)


def test_cold_raises_fleet_energy():
    """Plug-in probability AND session energy both rise with cold."""
    kwargs = dict(n_evs=200, res_minutes=15)
    cold = make_cold_coupled_ev_fleet(
        np.random.default_rng(2), temp_series=_series(24 * 10, -25.0), **kwargs
    )
    mild = make_cold_coupled_ev_fleet(
        np.random.default_rng(2), temp_series=_series(24 * 10, 15.0), **kwargs
    )
    assert cold.sum() > mild.sum() * 1.3


def test_annual_energy_lands_in_the_canadian_band():
    """~2 000-3 500 kWh/EV/yr (the old SDK model gave 6 567)."""
    idx = pd.date_range("2020-01-01", periods=8760, freq="h")
    # Seasonal swing: -15 C in January, +20 C in July.
    temp = pd.Series(
        2.5 - 17.5 * np.cos(2 * np.pi * np.arange(8760) / 8760.0), index=idx
    )
    fleet = make_cold_coupled_ev_fleet(
        np.random.default_rng(3), n_evs=60, temp_series=temp, res_minutes=15
    )
    kwh_per_ev = fleet.sum(axis=1) * 15 / 60.0
    assert 2000.0 <= float(kwh_per_ev.mean()) <= 3500.0


def test_is_deterministic():
    fleet_a = make_cold_coupled_ev_fleet(
        np.random.default_rng(4), n_evs=10, temp_series=_series(72, -10.0)
    )
    fleet_b = make_cold_coupled_ev_fleet(
        np.random.default_rng(4), n_evs=10, temp_series=_series(72, -10.0)
    )
    assert np.array_equal(fleet_a, fleet_b)


def test_supports_a_partial_28_hour_window():
    """A 28-hour window starting mid-day."""
    res = 5
    idx = pd.date_range("2020-01-15 12:00", periods=28 * 12, freq="5min")
    temp = pd.Series(np.full(len(idx), -20.0), index=idx)
    fleet = make_cold_coupled_ev_fleet(
        np.random.default_rng(5), n_evs=50, temp_series=temp, res_minutes=res
    )
    assert fleet.shape == (50, 28 * 12)
    assert fleet.sum() > 0.0
