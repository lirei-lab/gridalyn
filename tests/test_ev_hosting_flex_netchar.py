"""Tests for the network-characterization stage (losses / substation / headroom).

Tier 1 — hand-computed check of the crossing interpolator. Tier 2 — governed
reproduce-and-pin over the emitted characterization JSON (skipif absent).
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from projects.ev_hosting_flex.scripts.pipeline.analyze_network_characterization import (
    _interp_crossing,
)
from projects.ev_hosting_flex.scripts.config import PROJECT_OUTPUTS_DIR

_CHAR = PROJECT_OUTPUTS_DIR / "json" / "network_characterization.json"
_SKIP = (
    "network_characterization.json not present; run "
    "analyze_network_characterization.py first (outputs are gitignored)"
)


def test_interp_crossing_hand_computed() -> None:
    """Linear interpolation of the limit crossing, with edge cases."""
    pens = np.array([0.0, 0.5, 1.0, 1.5])
    # crosses 100 between 0.5 (90) and 1.0 (110) -> 0.75
    assert _interp_crossing(pens, np.array([80.0, 90.0, 110.0, 130.0]), 100.0) == (
        pytest.approx(0.75)
    )
    # already over at 0 EV -> 0.0
    assert _interp_crossing(pens, np.array([105.0, 110.0, 120.0, 130.0]), 100.0) == 0.0
    # never reaches -> inf
    assert np.isinf(_interp_crossing(pens, np.array([10.0, 20.0, 30.0, 40.0]), 100.0))


@pytest.mark.skipif(not _CHAR.is_file(), reason=_SKIP)
def test_governed_network_characterization() -> None:
    """Governed reproduce-and-pin: losses rise, N-1 substation robust, feeders bind.

    The substation is an HQ-realistic N-1 bank (3 x 20 MVA, ~62% loaded
    normally). Losses rise monotonically and super-linearly with EV load; the
    area peak load erodes the N-1 firm capacity — it crosses the NORMAL firm
    rating at a low penetration but never the EMERGENCY firm rating within the
    swept range, so a single-transformer contingency is survivable across all
    realistic adoption. The FEEDERS are the binding constraint for hosting, with
    a per-transformer headroom median near the study feeder's firm penetration
    (2 EVs / 6 homes = 0.33); the network is healthy before EVs.
    """
    payload = json.loads(_CHAR.read_text())
    loss = payload["losses"]["loss_percent"]
    assert loss == sorted(loss), "losses must rise with EV load"
    assert (loss[-1] - loss[-2]) > (loss[1] - loss[0])  # super-linear (I^2 R)
    sub = payload["substation"]
    # HQ-realistic N-1 bank: 3 transformers, ~62% loaded normally.
    assert sub["n_transformers"] == 3
    assert 50.0 < sub["normal_loading_percent"] < 75.0
    assert sub["firm_capacity_emergency_mw"] > sub["firm_capacity_normal_mw"]
    peak = sub["served_peak_mw"]
    assert peak == sorted(peak), "area peak load must rise with EV adoption"
    assert peak[0] < sub["firm_capacity_normal_mw"]  # healthy before EVs
    # N-1 survivable on emergency rating across the whole realistic sweep.
    assert sub["n1_reinforcement_penetration_normal"] is not None
    assert sub["n1_reinforcement_penetration_emergency"] is None
    hr = payload["headroom"]
    # the feeders are the binding hosting constraint.
    assert 0.0 < hr["crossing_penetration_p50"] < 1.0
    assert hr["crossing_penetration_p05"] <= hr["crossing_penetration_p50"]
    assert hr["crossing_penetration_p50"] <= hr["crossing_penetration_p95"]
    assert hr["n_overloaded_at_0ev"] == 0  # network healthy before EVs
