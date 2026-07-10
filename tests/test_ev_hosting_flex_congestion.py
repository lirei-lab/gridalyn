"""Unit + governed tests for the congestion-risk diagnostic stage.

Tiers: (1) hand-computed kernels, (2) a mini per-size assembly, (3) governed
reproduce-and-pin.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from projects.ev_hosting_flex.scripts._powerflow import congestion_stats


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
