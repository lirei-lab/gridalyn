"""Unit + governed tests for the credibility (confidence-interval) stage."""

from __future__ import annotations

import numpy as np


def test_winter_offsets_deterministic_and_anchored() -> None:
    """delta_0 = 0 (the nominal anchor); same seed -> same offsets."""
    from projects.ev_hosting_flex.scripts.pipeline.analyze_credibility import (
        winter_offsets,
    )

    a = winter_offsets(10, 1.5, 123)
    b = winter_offsets(10, 1.5, 123)
    assert a[0] == 0.0                         # realization 0 = nominal weather
    assert np.array_equal(a, b)                # deterministic
    assert len(a) == 10
    assert abs(float(np.std(a[1:]))) > 0.0     # the rest vary


def test_realization_headlines_types_and_cold_monotone() -> None:
    """firm/flex/breakeven are non-negative ints; a colder base does not raise
    firm (more load -> no more hosting)."""
    from projects.ev_hosting_flex.scripts.pipeline.analyze_credibility import (
        realization_headlines,
    )

    tday = np.full(365, -5.0)
    horizon = 365 * 96
    base = np.full(horizon, 40.0)          # 40 kW feeder base
    colder = np.full(horizon, 55.0)        # a colder year -> higher base
    pool = np.zeros((12, horizon))
    pool[:, ::96] = 6.0                     # a daily EV spike
    warm = realization_headlines(base, pool, tday, 71.25, 15, 0)
    cold = realization_headlines(colder, pool, tday, 71.25, 15, 0)
    for k in ("firm", "flex", "breakeven"):
        assert isinstance(warm[k], int) and warm[k] >= 0
    assert cold["firm"] <= warm["firm"]     # colder -> not more firm hosting


def test_stats_ordering_and_p_at_point() -> None:
    """P5 <= P50 <= P95 and p_at_point in [0, 1]."""
    from projects.ev_hosting_flex.scripts.pipeline.analyze_credibility import _stats

    st = _stats([2.0, 3.0, 3.0, 4.0, 3.0, 5.0], point=3.0)
    assert st["p05"] <= st["p50"] <= st["p95"]
    assert 0.0 <= st["p_at_point"] <= 1.0
    assert st["mode"] == 3.0
