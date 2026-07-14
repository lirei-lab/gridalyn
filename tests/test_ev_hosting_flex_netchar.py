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
    """Governed reproduce-and-pin: losses rise, N-1 substation binds, feeders bind.

    The substation is the standard HQ N-1 bank (2 identical parallel units,
    25 MVA each, ~60% loaded normally). Losses rise monotonically and
    super-linearly with EV load; on a single-unit contingency the lone survivor
    carries the all-electric base on its short-term EMERGENCY rating (the
    normal-rating firm capacity is below the base — precisely why a 2-unit N-1
    bank leans on the emergency rating), and the area peak load crosses that
    EMERGENCY firm capacity within the realistic adoption range, so the
    substation N-1 is itself a reinforcement trigger (unlike an over-built
    3-unit bank). The FEEDERS still bind first for hosting, with a
    per-transformer headroom median near the study feeder's firm penetration.
    On the realistic DHW-tank base (re-based 2026-07-14) the winter all-electric
    peak pushes 66/540 transformers over their STATIC rating at 0 EV — held by
    the C57.91 cold DYNAMIC uprating (0 over dynamic pre-EV), the real HQ posture.
    """
    payload = json.loads(_CHAR.read_text())
    loss = payload["losses"]["loss_percent"]
    assert loss == sorted(loss), "losses must rise with EV load"
    assert (loss[-1] - loss[-2]) > (loss[1] - loss[0])  # super-linear (I^2 R)
    sub = payload["substation"]
    # Standard HQ N-1 bank: 2 identical parallel units, ~56% loaded normally.
    assert sub["n_transformers"] == 2
    assert 50.0 < sub["normal_loading_percent"] < 65.0
    assert sub["firm_capacity_emergency_mw"] > sub["firm_capacity_normal_mw"]
    peak = sub["served_peak_mw"]
    assert peak == sorted(peak), "area peak load must rise with EV adoption"
    # With 2 units the single survivor carries the base on its EMERGENCY rating:
    # healthy before EVs at emergency, but over the normal firm rating from the
    # start (that is the design intent of a 2-unit N-1 bank, not a violation).
    assert peak[0] < sub["firm_capacity_emergency_mw"]  # healthy before EVs (N-1 emerg.)
    assert peak[0] > sub["firm_capacity_normal_mw"]
    # The N-1 emergency contingency is a real reinforcement trigger in range.
    assert sub["n1_reinforcement_penetration_normal"] == 0.0
    assert sub["n1_reinforcement_penetration_emergency"] is not None
    assert sub["n1_reinforcement_penetration_emergency"] > 0.0
    hr = payload["headroom"]
    # the feeders are the binding hosting constraint.
    assert 0.0 < hr["crossing_penetration_p50"] < 1.0
    assert hr["crossing_penetration_p05"] <= hr["crossing_penetration_p50"]
    assert hr["crossing_penetration_p50"] <= hr["crossing_penetration_p95"]
    assert hr["n_overloaded_at_0ev"] == 66  # over STATIC pre-EV; 0 over dynamic
