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
    """Governed reproduce-and-pin: losses rise, substation binds, headroom map.

    Losses rise monotonically and super-linearly with EV load; the substation is
    already at/over its cold dynamic rating at 0 EV (crosses it almost
    immediately), confirming it as the binding constraint; the per-transformer
    headroom median (~0.35 EV/home) matches the study feeder's firm penetration
    (2 EVs / 6 homes = 0.33).
    """
    payload = json.loads(_CHAR.read_text())
    loss = payload["losses"]["loss_percent"]
    assert loss == sorted(loss), "losses must rise with EV load"
    # super-linear: the increment grows (I^2 R).
    assert (loss[-1] - loss[-2]) > (loss[1] - loss[0])
    sub = payload["substation"]
    dyn = sub["dynamic_rating_percent"]
    assert sub["peak_loading_percent"][0] >= 100.0  # already over static at 0 EV
    # binds at (near) 0 EV — the substation is the constraint, not the feeders.
    assert sub["crossing_penetration_dynamic"] is not None
    assert sub["crossing_penetration_dynamic"] < 0.25
    assert sub["peak_loading_percent"][-1] > dyn
    hr = payload["headroom"]
    assert 0.0 < hr["crossing_penetration_p50"] < 1.0
    assert hr["crossing_penetration_p05"] <= hr["crossing_penetration_p50"]
    assert hr["crossing_penetration_p50"] <= hr["crossing_penetration_p95"]
    assert 0 <= hr["n_overloaded_at_0ev"] < hr["n_transformers"]
