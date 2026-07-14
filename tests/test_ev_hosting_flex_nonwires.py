"""Unit + governed tests for the pilar-2 network non-wires value stage."""

from __future__ import annotations

import numpy as np
import pytest

from projects.ev_hosting_flex.scripts._powerflow import flex_deferral_curves


def test_flex_deferral_curves_shapes_and_monotone() -> None:
    """peak_noflex rises with adoption; curtailed_frac is 0 until the flexed
    peak binds, then rises; the flex caps the no-flex overload."""
    # a flat 6 kW/home base with a 5 kW/home evening EV spike, 6 homes, 50 kW rating
    base = np.full(24, 6.0)
    ev = np.zeros(24)
    ev[18:22] = 5.0  # per-EV evening kW
    grid = np.array([0.0, 0.5, 1.0, 1.5, 2.0])
    out = flex_deferral_curves(base, ev, 6, 50.0, grid)
    assert out["peak_noflex"].shape == (5,)
    assert list(out["peak_noflex"]) == sorted(out["peak_noflex"])  # rises
    assert out["curtailed_frac"][0] == 0.0                          # no EV -> none
    assert out["curtailed_frac"][-1] >= out["curtailed_frac"][0]    # rises
    assert (out["curtailed_frac"] >= 0.0).all()


def test_ramp_monotone_and_invertible() -> None:
    """The logistic ramp rises 0->max and year_at is its inverse."""
    from projects.ev_hosting_flex.scripts._annual import (
        adoption_at_year,
        year_at_adoption,
    )
    from projects.ev_hosting_flex.scripts.config import RAMP_MAX_EV_PER_HOME

    ys = np.linspace(0, 15, 16)
    ad = np.array([adoption_at_year(float(y)) for y in ys])
    assert list(ad) == sorted(ad)                       # non-decreasing
    assert ad[0] < ad[-1] <= RAMP_MAX_EV_PER_HOME + 1e-9
    # invertible on the interior
    for y in (2.0, 5.0, 9.0, 12.0):
        assert year_at_adoption(adoption_at_year(y)) == pytest.approx(y, abs=1e-6)
    # boundary: adoption >= max -> +inf (never reached); <= 0 -> year 0
    assert year_at_adoption(RAMP_MAX_EV_PER_HOME) == float("inf")
    assert year_at_adoption(0.0) == 0.0
