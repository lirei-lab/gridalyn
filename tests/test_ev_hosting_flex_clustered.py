"""Unit + governed tests for the clustered-adoption stage (Study 3B).

Three tiers, mirroring the project convention:
1. HAND-COMPUTED KERNEL TESTS — gini / draw_clustered_adoption /
   apply_local_curtailment, cache-free.
2. MINI-NET CONVERGENCE — a small hand-built full net through the per-draw
   solve helper.
3. GOVERNED REPRODUCE-AND-PIN — reads the emitted clustered_adoption.json
   (skipif absent) and asserts the penalty/recovery invariants.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from projects.ev_hosting_flex.scripts._powerflow import gini


def test_gini_hand_computed() -> None:
    """Gini is 0 for a uniform vector and rises with concentration."""
    assert gini(np.array([5.0, 5.0, 5.0, 5.0])) == pytest.approx(0.0, abs=1e-12)
    # all mass on one element of n -> (n-1)/n
    assert gini(np.array([0.0, 0.0, 0.0, 4.0])) == pytest.approx(0.75, abs=1e-9)
    # known value: [1,2,3,4] -> 0.25
    assert gini(np.array([1.0, 2.0, 3.0, 4.0])) == pytest.approx(0.25, abs=1e-9)
    assert gini(np.array([0.0, 0.0])) == 0.0  # degenerate: zero sum


def test_draw_clustered_adoption_mean_preserving_and_monotone() -> None:
    """delta=0 gives uniform; fleet is preserved; Gini rises with dispersion."""
    from projects.ev_hosting_flex.scripts._powerflow import draw_clustered_adoption

    rng = np.random.default_rng(42)
    homes = np.array([6, 6, 8, 4, 10, 5, 7, 3, 6, 9], dtype=float)
    mu = 1.0

    # delta = 0 -> exactly uniform
    a0 = draw_clustered_adoption(homes, mu, 0.0, rng)
    assert np.allclose(a0, mu)

    # home-weighted mean (fleet / homes) preserved for every dispersion
    ginis = []
    for delta in (0.0, 0.35, 0.7, 1.1):
        acc = []
        for _ in range(200):
            a = draw_clustered_adoption(homes, mu, delta, rng)
            fleet_mean = float(np.sum(a * homes) / homes.sum())
            assert fleet_mean == pytest.approx(mu, rel=1e-9)
            assert np.all(a >= 0.0)
            acc.append(gini(a))
        ginis.append(float(np.mean(acc)))
    # mean Gini strictly increases with dispersion
    assert ginis == sorted(ginis)
    assert ginis[0] == pytest.approx(0.0, abs=1e-12)
    assert ginis[-1] > 0.1
