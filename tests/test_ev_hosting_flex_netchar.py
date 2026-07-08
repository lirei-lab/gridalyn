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
    """Governed reproduce-and-pin: losses rise, substation healthy, feeders bind.

    With the HQ-load-matched substation transformers (bibliographic
    verification: real 120/25 kV units are 33-140 MVA, not the synthetic 15),
    the network is design-cold-healthy BEFORE EVs at every level: losses rise
    monotonically and super-linearly with EV load; the substation is loaded but
    below its static nameplate at 0 EV and stays within its cold dynamic rating
    across the swept range (it is NO longer the binding constraint); the FEEDERS
    bind first, with a per-transformer headroom median matching the study
    feeder's firm penetration (2 EVs / 6 homes = 0.33).
    """
    payload = json.loads(_CHAR.read_text())
    loss = payload["losses"]["loss_percent"]
    assert loss == sorted(loss), "losses must rise with EV load"
    # super-linear: the increment grows (I^2 R).
    assert (loss[-1] - loss[-2]) > (loss[1] - loss[0])
    sub = payload["substation"]
    dyn = sub["dynamic_rating_percent"]
    # HQ-load-matched: healthy (< nameplate) at 0 EV, rises with adoption.
    assert sub["peak_loading_percent"][0] < 100.0
    assert sub["peak_loading_percent"][-1] > sub["peak_loading_percent"][0]
    # sized so it never crosses its cold dynamic rating over the swept range.
    assert sub["crossing_penetration_dynamic"] is None
    assert sub["peak_loading_percent"][-1] <= dyn
    hr = payload["headroom"]
    # the feeders are the binding constraint (median headroom ~ the firm pen).
    assert 0.0 < hr["crossing_penetration_p50"] < 1.0
    assert hr["crossing_penetration_p05"] <= hr["crossing_penetration_p50"]
    assert hr["crossing_penetration_p50"] <= hr["crossing_penetration_p95"]
    # network healthy before EVs: no transformer over its static nameplate.
    assert hr["n_overloaded_at_0ev"] == 0
