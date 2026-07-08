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
    ev_energy = np.array([20.0, 12.0], dtype=float)  # two EVs, 32 kWh total
    charger = np.array([7.2, 7.2], dtype=float)  # aggregate 14.4 kW/h cap
    agg = valley_fill_shift(net, ev_energy, rating, charger)
    assert float(agg.sum()) == pytest.approx(32.0)  # energy preserved
    assert np.all(agg[4:] == 0.0)  # nothing added to the peak
    assert (net + agg).max() <= 60.0 + 1e-9  # peak not raised
    # no valley: flat load already near the rating -> energy must stack, peak rises
    flat = np.full(6, 66.0, dtype=float)
    agg2 = valley_fill_shift(flat, ev_energy, rating, charger)
    assert float(agg2.sum()) == pytest.approx(32.0)  # still energy-preserving
    assert (flat + agg2).max() > rating  # shift cannot relieve


def test_wta_helpers_are_monotone_inverses() -> None:
    """Enrollment rises with incentive; price(enrollment) inverts it."""
    from projects.ev_hosting_flex.scripts.pipeline.analyze_flexibility_incentive import (
        wta_enrollment,
        wta_price_for_enrollment,
    )

    med, sig = 100.0, 0.5
    # at the median incentive, half enrol
    assert wta_enrollment(med, med, sig) == pytest.approx(0.5, abs=1e-6)
    # monotone increasing in incentive
    assert wta_enrollment(50.0, med, sig) < wta_enrollment(150.0, med, sig)
    # inverse round-trips
    p = wta_price_for_enrollment(0.8, med, sig)
    assert wta_enrollment(p, med, sig) == pytest.approx(0.8, abs=1e-6)
    # curtailment (higher median) costs more for the same enrollment
    assert wta_price_for_enrollment(0.8, 120.0, sig) > wta_price_for_enrollment(
        0.8, 30.0, sig
    )


def test_bin_p95_loading_valley_vs_flat() -> None:
    """Shift relieves when a valley exists and barely helps when the base is flat."""
    from projects.ev_hosting_flex.scripts.pipeline.analyze_flexibility_incentive import (
        _bin_p95_loading,
    )

    rating = 70.0
    hours = 24
    # base with a deep valley (low 0-15h, moderate evening) vs a flat-high base
    valley_base = np.full(hours, 20.0)
    valley_base[16:22] = 45.0
    flat_base = np.full(hours, 60.0)

    # one bin, one day (day 0); build a 2-day hourly base so index math works
    def two_day(profile):
        return np.concatenate([profile, profile]).astype(float)

    # pool: 3 EVs each 8 kWh in the evening
    pool = np.zeros((3, hours * 2), dtype=float)
    for e in range(3):
        pool[e, 16:20] = 2.0  # 8 kWh in the evening, day 0
    charger = np.full(3, 7.2)
    args = dict(
        day_indices=[0],
        n_ev=3,
        n_enrolled=3,
        rating_kw=rating,
        hod0=0,
        charger_kw=charger,
        evening=(16, 22),
    )
    for policy, base in (("valley", valley_base), ("flat", flat_base)):
        p_unc = _bin_p95_loading(
            base=two_day(base), pool=pool, policy="uncontrolled", **args
        )
        p_shift = _bin_p95_loading(
            base=two_day(base), pool=pool, policy="shift", **args
        )
        if policy == "valley":
            assert p_shift < p_unc - 5.0  # shift relieves materially
        else:
            assert p_shift >= p_unc - 1.0  # flat base: shift barely helps
    # curtail always caps to <= 100% of rating
    p_cur = _bin_p95_loading(
        base=two_day(flat_base), pool=pool, policy="curtail", **args
    )
    assert p_cur <= 100.0 + 1e-6
