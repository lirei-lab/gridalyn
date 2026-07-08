"""Unit + governed tests for the flexibility-incentive stage (Study 1A).

Tiers: (1) hand-computed kernels (climate binning, valley-fill, WTA), (2) a
mini physical engine (clear valley vs flat), (3) governed reproduce-and-pin.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from projects.ev_hosting_flex.scripts._annual import climate_bin_days


def test_climate_bin_days_hand_built() -> None:
    """Days are grouped into half-open temp bins; the median-temp day is picked."""
    # 5 days: mean temps -22, -18, -17, -3, +2  (hourly series, 24 h/day)
    means = [-22.0, -18.0, -17.0, -3.0, 2.0]
    temp = pd.Series(np.repeat(means, 24).astype(float))
    bins = climate_bin_days(temp, (-25.0, -20.0, -15.0, 0.0, 5.0))
    # bin [-25,-20): day 0 ; [-20,-15): days 1,2 (median-temp -> the -18 day=1);
    # [-15,0): day 3 ; [0,5): day 4
    by_lo = {b["bin_lo"]: b for b in bins}
    assert by_lo[-25.0]["day_idx"] == 0 and by_lo[-25.0]["n_days"] == 1
    assert by_lo[-20.0]["n_days"] == 2 and by_lo[-20.0]["day_idx"] == 1
    assert by_lo[-15.0]["day_idx"] == 3
    assert by_lo[0.0]["day_idx"] == 4
    # empty bins are omitted
    assert all(b["n_days"] > 0 for b in bins)
    # each entry carries the bin's day-index membership for the P95 over days
    assert sorted(by_lo[-20.0]["day_indices"]) == [1, 2]


def test_valley_fill_shift_fills_valley_and_preserves_energy() -> None:
    """Energy goes to the lowest-load hours; total energy is exactly preserved."""
    from projects.ev_hosting_flex.scripts._annual import valley_fill_shift

    # clear valley: high in the evening (hours 4-5), low at night (0-3)
    net = np.array([10.0, 10.0, 10.0, 10.0, 60.0, 60.0], dtype=float)
    rating = 70.0
    ev_energy = np.array([20.0, 12.0], dtype=float)   # two EVs, 32 kWh total
    charger = np.array([7.2, 7.2], dtype=float)       # aggregate 14.4 kW/h cap
    agg = valley_fill_shift(net, ev_energy, rating, charger)
    assert float(agg.sum()) == pytest.approx(32.0)          # energy preserved
    assert np.all(agg[4:] == 0.0)                           # nothing added to the peak
    assert (net + agg).max() <= 60.0 + 1e-9                 # peak not raised
    # no valley: flat load already near the rating -> energy must stack, peak rises
    flat = np.full(6, 66.0, dtype=float)
    agg2 = valley_fill_shift(flat, ev_energy, rating, charger)
    assert float(agg2.sum()) == pytest.approx(32.0)         # still energy-preserving
    assert (flat + agg2).max() > rating                     # shift cannot relieve
