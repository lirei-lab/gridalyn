"""Unit + governed tests for the pilar-2 network non-wires value stage."""

from __future__ import annotations

import numpy as np

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
