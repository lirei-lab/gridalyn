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
