"""Unit + governed tests for the congestion-risk diagnostic stage.

Tiers: (1) hand-computed kernels, (2) a mini per-size assembly, (3) governed
reproduce-and-pin.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from projects.ev_hosting_flex.scripts._powerflow import (
    _cold_day_peaks,
    congestion_stats,
)


def test_congestion_stats_hand_computed() -> None:
    """Congestion probability + peak-severity tail (percentiles in % of rating)."""
    # peaks 50/90/110/130 kW on a 100 kW rating -> 50/90/110/130 %
    s = congestion_stats(np.array([50.0, 90.0, 110.0, 130.0]), 100.0)
    assert s["p_cong"] == pytest.approx(0.5)       # 110, 130 exceed 100
    assert s["peak_p50"] == pytest.approx(100.0)   # median of 50/90/110/130
    assert s["peak_max"] == pytest.approx(130.0)
    assert s["peak_p99"] >= s["peak_p95"] >= s["peak_p50"]
    # nothing over the rating -> zero probability
    s0 = congestion_stats(np.array([10.0, 20.0, 30.0]), 100.0)
    assert s0["p_cong"] == 0.0


def test_cold_day_peaks_hand_computed() -> None:
    """Daily coincident max over the cold days only."""
    # 2 days, 4 steps/day; day 0 cold, day 1 warm
    load = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 9.0, 6.0, 2.0])
    peaks = _cold_day_peaks(load, np.array([True, False]), 4)
    assert peaks.tolist() == [4.0]           # cold day 0's max
    peaks2 = _cold_day_peaks(load, np.array([False, True]), 4)
    assert peaks2.tolist() == [9.0]          # cold day 1's max
    both = _cold_day_peaks(load, np.array([True, True]), 4)
    assert both.tolist() == [4.0, 9.0]


def test_size_congestion_mini() -> None:
    """A mini per-size assembly: P(cong) rises with G and with EV adoption."""
    from projects.ev_hosting_flex.scripts.pipeline.analyze_congestion_risk import (
        _size_congestion,
    )

    steps_per_day = 4
    # 2 days both cold; one base realization for a 1-home size, peak 40 kW/day
    base_mc = np.array([[10.0, 20.0, 40.0, 5.0, 12.0, 22.0, 38.0, 6.0]])  # (1, 8)
    # one EV draw of 2 EVs, each adding a 20 kW spike at step 2 (the base peak hr)
    ev_pools = [np.array([[0, 0, 20.0, 0, 0, 0, 20.0, 0],
                          [0, 0, 20.0, 0, 0, 0, 20.0, 0]])]  # (2, 8)
    cold = np.array([True, True])
    rating = 70.0
    # 0 EV, G=1: base peak 40 -> 57% -> no congestion
    s00 = _size_congestion(base_mc, ev_pools, cold, steps_per_day, homes=1,
                           rating_kw=rating, g=1.0, ev_per_home=0.0)
    assert s00["p_cong"] == 0.0
    # 2 EV/home, G=1: base 40 + 40 EV = 80 > 70 -> congested
    s2 = _size_congestion(base_mc, ev_pools, cold, steps_per_day, homes=1,
                          rating_kw=rating, g=1.0, ev_per_home=2.0)
    assert s2["p_cong"] == 1.0
    # growth raises the peak severity monotonically at fixed adoption
    lo = _size_congestion(base_mc, ev_pools, cold, steps_per_day, homes=1,
                          rating_kw=rating, g=1.0, ev_per_home=1.0)
    hi = _size_congestion(base_mc, ev_pools, cold, steps_per_day, homes=1,
                          rating_kw=rating, g=1.2, ev_per_home=1.0)
    assert hi["peak_max"] >= lo["peak_max"]
