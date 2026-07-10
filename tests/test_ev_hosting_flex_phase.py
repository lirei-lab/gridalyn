"""Unit + governed tests for the phase-imbalance diagnostic stage.

Tiers: (1) hand-computed kernel, (2) mini 3-phase net convergence, (3) governed
reproduce-and-pin.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from projects.ev_hosting_flex.scripts._powerflow import vuf


def test_vuf_hand_computed() -> None:
    """Voltage unbalance factor = max deviation from the mean, over the mean (%)."""
    assert vuf(1.0, 1.0, 1.0) == pytest.approx(0.0)          # balanced -> 0
    # phases 0.90 / 1.00 / 1.00: mean 0.9667, max dev 0.0667 -> 6.897 %
    assert vuf(0.90, 1.00, 1.00) == pytest.approx(0.0667 / 0.96667 * 100.0, abs=5e-3)
