"""Unit + governed tests for the network-performance stage.

Tiers: (1) hand-computed kernels, (2) a mini per-transformer panel across G,
(3) governed reproduce-and-pin.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from projects.ev_hosting_flex.scripts._powerflow import (
    annual_performance_metrics,
    flexible_share,
)


def test_annual_performance_metrics_hand_computed() -> None:
    """Utilization, load factor, exceedance counts, headroom, growth margin."""
    # rating 100 kW; a healthy element (peak 90) and an overloaded one (peak 120)
    healthy = annual_performance_metrics(np.array([40.0, 60.0, 80.0, 90.0]), 100.0)
    assert healthy["peak_utilization_pct"] == pytest.approx(90.0)
    assert healthy["load_factor"] == pytest.approx(67.5 / 90.0)
    assert healthy["hours_over_90"] == 0     # strictly greater than 90 kW
    assert healthy["hours_over_100"] == 0
    assert healthy["min_headroom_kw"] == pytest.approx(10.0)
    assert healthy["growth_margin_pct"] == pytest.approx((100.0 / 90.0 - 1) * 100.0)

    over = annual_performance_metrics(np.array([40.0, 95.0, 105.0, 120.0]), 100.0)
    assert over["peak_utilization_pct"] == pytest.approx(120.0)
    assert over["hours_over_90"] == 3        # 95, 105, 120 all exceed 90
    assert over["hours_over_100"] == 2       # 105, 120 exceed 100
    assert over["min_headroom_kw"] == pytest.approx(-20.0)
    assert over["growth_margin_pct"] == pytest.approx((100.0 / 120.0 - 1) * 100.0)


def test_flexible_share_hand_computed() -> None:
    """Flexible (EV) fraction of the peak; 0 when there is no load."""
    assert flexible_share(90.0, 10.0) == pytest.approx(0.1)
    assert flexible_share(50.0, 50.0) == pytest.approx(0.5)
    assert flexible_share(0.0, 0.0) == 0.0
