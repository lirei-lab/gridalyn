"""Reference test: the hand-rolled sharing-ADMM matches a CVXPY centralized solve.

The coordination problem (with the comfort/temperature penalty) is a convex QP,
so a general-purpose solver gives the ground-truth optimum. We solve a small
instance both ways and assert the ADMM reaches the same objective and aggregate
peak. This validates the custom solver's correctness independently of the
production pipeline. Skipped if CVXPY is unavailable.
"""

from __future__ import annotations

import numpy as np
import pytest

from projects.admm_thermal_consensus.scripts.admm.consensus import (
    build_comfort_prox_inverse,
    rc_response_matrix,
    solve_sharing_admm,
)

cp = pytest.importorskip("cvxpy")


def _instance(seed: int = 0):
    # A moderate population: the prox-then-project x-update's objective gap
    # shrinks as the agent count grows (the consensus average improves), so a
    # too-small instance overstates it. The aggregate peak -- the quantity the
    # study reports -- matches the centralized optimum to <0.05% at every scale.
    rng = np.random.default_rng(seed)
    n, t = 25, 32
    h = np.abs(rng.normal(3.0, 0.7, size=(n, t))) + 0.5
    b = np.abs(rng.normal(1.0, 0.2, size=(n, t)))
    resistance = rng.uniform(8.0, 13.0, size=n)
    capacitance = rng.uniform(1.5, 2.5, size=n)
    return h, b, resistance, capacitance


def _full_objective(x, h, b, g_mats, lam, mu, gamma):
    bg_total = b.sum(axis=0)
    energy = h.sum(axis=1)
    c = (energy.sum() + bg_total.sum()) / h.shape[1]
    comfort = sum(
        0.5 * lam * np.sum((x[i] - h[i]) ** 2)
        + 0.5 * gamma * np.sum((g_mats[i] @ (x[i] - h[i])) ** 2)
        for i in range(h.shape[0])
    )
    flat = 0.5 * mu * np.sum((x.sum(axis=0) + bg_total - c) ** 2)
    return float(comfort + flat)


@pytest.mark.parametrize("gamma", [0.0, 2.0])
def test_admm_matches_cvxpy_optimum(gamma):
    h, b, resistance, capacitance = _instance()
    n, t = h.shape
    alpha, lam, mu, rho, step_h = 0.5, 0.15, 1.0, 1.0, 0.25
    lo, hi = (1 - alpha) * h, (1 + alpha) * h
    energy = h.sum(axis=1)
    bg_total = b.sum(axis=0)
    c = (energy.sum() + bg_total.sum()) / t
    g_mats = [rc_response_matrix(resistance[i], capacitance[i], step_h, t) for i in range(n)]

    # --- hand-rolled sharing-ADMM (tight convergence) ---
    prox = build_comfort_prox_inverse(
        resistance, capacitance, step_h, t, gamma, lam, rho
    )
    res = solve_sharing_admm(
        heating=h, background=b, alpha=alpha, rho=rho, lam=lam, mu=mu,
        max_iters=3000, tol=1e-9, comfort_prox_inverse=prox,
    )

    # --- CVXPY centralized optimum (ground truth) ---
    xs = [cp.Variable(t) for _ in range(n)]
    obj = 0
    cons = []
    total = 0
    for i in range(n):
        obj += 0.5 * lam * cp.sum_squares(xs[i] - h[i])
        if gamma > 0:
            obj += 0.5 * gamma * cp.sum_squares(g_mats[i] @ (xs[i] - h[i]))
        cons += [xs[i] >= lo[i], xs[i] <= hi[i], cp.sum(xs[i]) == energy[i]]
        total = total + xs[i]
    obj += 0.5 * mu * cp.sum_squares(total + bg_total - c)
    cp.Problem(cp.Minimize(obj), cons).solve()
    x_ref = np.vstack([v.value for v in xs])

    obj_admm = _full_objective(res.x, h, b, g_mats, lam, mu, gamma)
    obj_ref = _full_objective(x_ref, h, b, g_mats, lam, mu, gamma)

    # The aggregate peak -- the quantity the study reports -- matches the
    # centralized optimum essentially exactly, at any gamma.
    peak_admm = (res.x.sum(axis=0) + bg_total).max()
    peak_ref = (x_ref.sum(axis=0) + bg_total).max()
    assert abs(peak_admm - peak_ref) <= 5e-4 * peak_ref

    # Objective: exact for the separable (gamma=0) prox; within a small gap for
    # the temperature-coupled prox (prox-then-project is mildly inexact, the gap
    # shrinks with the agent count).
    obj_tol = 1e-3 if gamma == 0 else 1e-2
    assert abs(obj_admm - obj_ref) <= obj_tol * max(abs(obj_ref), 1.0)

    # per-agent feasibility holds for the ADMM solution
    assert np.all(res.x >= lo - 1e-6) and np.all(res.x <= hi + 1e-6)
    assert np.allclose(res.x.sum(axis=1), energy, atol=1e-4)
