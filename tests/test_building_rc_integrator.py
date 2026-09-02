"""Tests for the opt-in exact-discrete RC integrator in Building.step.

The default forward-Euler path must stay byte-identical (pinned T_in regression
anchor), while the opt-in ``integrator="exact"`` path uses the exact-discrete RC
update and lands between the old temperature and the analytic equilibrium.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from gridalyn.assets.datagen.agents.buildings import ETA_COOL, ETA_HEAT, Building

# T_in after 20 fixed euler steps (seed 7, t_out=-15, p_bg=1.2, dt=15) captured
# from the CURRENT forward-Euler code. Pins the default path against drift.
_REF_T_IN_AFTER_20 = 21.007758355684327
_REF_T_IN_FIRST3 = (
    23.162084688099014,
    22.758652498935056,
    22.35948521124553,
)


def _run_sequence(building: Building, *, integrator: str | None = None) -> list[float]:
    """Run a fixed 20-step sequence, returning the per-step T_in trajectory."""
    out: list[float] = []
    for k in range(20):
        kwargs = {} if integrator is None else {"integrator": integrator}
        result = building.step(
            t_out=-15.0,
            minute_of_day=float((k * 15) % 1440),
            p_bg_kw=1.2,
            dt_min=15.0,
            **kwargs,
        )
        out.append(result["T_in_C"])
    return out


def test_euler_default_byte_identical() -> None:
    """Default args and integrator='euler' both match the pinned euler anchor."""
    b_default = Building(unit_id=0, rng=np.random.default_rng(7))
    traj_default = _run_sequence(b_default)

    b_euler = Building(unit_id=0, rng=np.random.default_rng(7))
    traj_euler = _run_sequence(b_euler, integrator="euler")

    assert traj_default == traj_euler
    assert b_default.T_in == b_euler.T_in
    # Regression anchor: default path is byte-identical to the captured euler run.
    assert b_default.T_in == _REF_T_IN_AFTER_20
    assert tuple(traj_default[:3]) == _REF_T_IN_FIRST3


def test_exact_path_opt_in_differs_but_tracks() -> None:
    """Exact one-step lands between T_old and T_eq, and differs from euler."""
    b_euler = Building(unit_id=0, rng=np.random.default_rng(7))
    traj_euler = _run_sequence(b_euler, integrator="euler")

    b_exact = Building(unit_id=0, rng=np.random.default_rng(7))
    traj_exact = _run_sequence(b_exact, integrator="exact")

    # Opt-in actually changes the path on at least one step.
    assert any(e != x for e, x in zip(traj_euler, traj_exact, strict=True))

    # One controlled step: exact lands strictly between T_old and the analytic
    # equilibrium T_eq for a heating-dominated forcing.
    b = Building(unit_id=5, rng=np.random.default_rng(3))
    b.T_in = 15.0  # well below setpoint -> heating engages
    t_out = -10.0
    result = b.step(
        t_out=t_out, minute_of_day=0.0, p_bg_kw=1.0, dt_min=15.0, integrator="exact"
    )
    p_heat = result["p_heat_kw"]
    p_cool = result["p_cool_kw"]
    t_eq = t_out + b.R * (ETA_HEAT * p_heat - ETA_COOL * p_cool)
    t_new = result["T_in_C"]
    # Heating from below pushes T_in up toward (but not past) T_eq.
    assert 15.0 < t_new < t_eq
    # Sanity: matches the exact-discrete closed form.
    tau = b.R * b.C
    expected = 15.0 + (1.0 - math.exp(-(15.0 / 60.0) / tau)) * (t_eq - 15.0)
    assert t_new == pytest.approx(expected)


def test_invalid_integrator_raises() -> None:
    """An unsupported integrator raises a located ValueError naming the options."""
    b = Building(unit_id=0, rng=np.random.default_rng(7))
    with pytest.raises(ValueError) as excinfo:
        b.step(t_out=-15.0, minute_of_day=0.0, p_bg_kw=1.2, integrator="rk4")
    message = str(excinfo.value)
    assert "rk4" in message
    assert "euler" in message
    assert "exact" in message
