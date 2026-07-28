"""Tests for the SDK domestic-hot-water tank fleet generator."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from gridalyn.assets.datagen.agents import (
    DHWTankParams,
    dhw_draw_profile,
    make_dhw_tank_fleet,
)


def _series(hours: int, temp_c: float, start: str = "2020-01-01 00:00") -> pd.Series:
    idx = pd.date_range(start, periods=hours, freq="h")
    return pd.Series(np.full(hours, float(temp_c)), index=idx)


def test_draw_profile_is_a_normalised_all_day_curve():
    """No zero hours: a flat-zero hour would re-synchronise the reheats."""
    weights = dhw_draw_profile()
    assert weights.shape == (24,)
    assert weights.sum() == pytest.approx(1.0)
    assert weights.min() > 0.0
    # Morning and evening occupancy peaks, evening the larger of the two.
    assert weights[19] > weights[7] > weights[3]


def test_daily_energy_per_home_is_physical():
    """~180 L/day from ~11 C inlet to 60 C is roughly 8-13 kWh/home/day."""
    res = 15
    fleet = make_dhw_tank_fleet(
        np.random.default_rng(0),
        n_homes=200,
        temp_series=_series(24 * 5, -10.0),
        res_minutes=res,
    )
    kwh_per_home_day = fleet.sum() * res / 60.0 / 200 / 5
    assert 8.0 <= float(kwh_per_home_day) <= 13.0


def test_per_home_jitter_staggers_the_first_reheat():
    """Identical tanks all cut in on the same step; jitter must spread them.

    Guards the 2026-07-16 realism fix. Every tank starts full and drains at a
    similar rate, so without per-home diversity the whole fleet crosses its
    cut-in temperature on the SAME step and the aggregate shows a switching
    spike that stochastic aggregation should never produce.

    Measured on the FIRST reheat cycle, where the effect is undiluted. A flat
    threshold on the aggregate's step-to-step slope does NOT work: that slope
    is dominated by the occupancy curve, which every home legitimately shares,
    so it is present with or without jitter.
    """
    res = 15
    temp = _series(24 * 3, -10.0)
    identical = DHWTankParams(
        setpoint_jitter_c=0.0,
        deadband_jitter_c=0.0,
        element_jitter_kw=0.0,
        tank_l_jitter_l=0.0,
        daily_l_std=0.0,
    )

    def first_cycle_peak_ratio(params: DHWTankParams | None) -> float:
        peaks = []
        for seed in (0, 1, 2):
            fleet = make_dhw_tank_fleet(
                np.random.default_rng(seed),
                n_homes=300,
                temp_series=temp,
                res_minutes=res,
                params=params,
            )
            peaks.append(float(fleet[:32].max() / fleet.mean()))
        return float(np.mean(peaks))

    jittered = first_cycle_peak_ratio(None)
    synchronised = first_cycle_peak_ratio(identical)
    assert jittered < 0.9 * synchronised


def test_reheat_peak_follows_the_local_clock_not_the_array_position():
    """Phase anchor: a window starting 19:00 must still peak near the evening.

    Guards the phase bug where draw weights were indexed by array position and
    the peak landed ~5 h early.
    """
    res = 60
    idx = pd.date_range("2020-01-01 19:00", periods=48, freq="h")
    temp = pd.Series(np.full(48, -10.0), index=idx)
    fleet = make_dhw_tank_fleet(
        np.random.default_rng(2), n_homes=300, temp_series=temp, res_minutes=res
    )
    # Fold onto the local clock hour and check the evening peak.
    by_hour = np.zeros(24)
    for k in range(len(fleet)):
        by_hour[(19 + k) % 24] += float(fleet[k])
    assert int(by_hour.argmax()) in (18, 19, 20, 21)


def test_is_deterministic():
    fleet_a = make_dhw_tank_fleet(
        np.random.default_rng(3), n_homes=25, temp_series=_series(48, -5.0)
    )
    fleet_b = make_dhw_tank_fleet(
        np.random.default_rng(3), n_homes=25, temp_series=_series(48, -5.0)
    )
    assert np.array_equal(fleet_a, fleet_b)


def test_supports_a_partial_28_hour_window_at_5_minutes():
    res = 5
    idx = pd.date_range("2020-01-15 12:00", periods=28 * 12, freq="5min")
    temp = pd.Series(np.full(len(idx), -20.0), index=idx)
    fleet = make_dhw_tank_fleet(
        np.random.default_rng(4), n_homes=100, temp_series=temp, res_minutes=res
    )
    assert fleet.shape == (28 * 12,)
    assert fleet.sum() > 0.0
