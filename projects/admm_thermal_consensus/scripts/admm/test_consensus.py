"""Unit tests for the sharing-ADMM thermal consensus solver."""

from __future__ import annotations

import numpy as np

from projects.admm_thermal_consensus.scripts.admm.consensus import (
    AdmmResult,
    project_capped_energy,
    solve_sharing_admm,
)


def test_project_capped_energy_respects_box_and_total():
    q = np.array([0.0, 5.0, 10.0, 2.0])
    lo = np.array([1.0, 1.0, 1.0, 1.0])
    hi = np.array([4.0, 4.0, 4.0, 4.0])
    x = project_capped_energy(q, lo, hi, total=10.0)
    assert np.all(x >= lo - 1e-9)
    assert np.all(x <= hi + 1e-9)
    assert abs(x.sum() - 10.0) < 1e-6


def test_admm_conserves_energy_and_respects_box_per_agent():
    rng = np.random.default_rng(0)
    T, N = 24, 6
    h = np.abs(rng.normal(3.0, 0.7, size=(N, T))) + 0.5
    b = np.abs(rng.normal(1.0, 0.2, size=(N, T)))
    res = solve_sharing_admm(
        heating=h, background=b, alpha=0.5, rho=1.0, lam=0.1, mu=1.0,
        max_iters=400, tol=1e-5,
    )
    assert isinstance(res, AdmmResult)
    # energy conserved per agent
    assert np.allclose(res.x.sum(axis=1), h.sum(axis=1), atol=1e-3)
    # box respected per agent
    assert np.all(res.x >= 0.5 * h - 1e-3)
    assert np.all(res.x <= 1.5 * h + 1e-3)


def test_admm_reduces_peak_vs_uncoordinated():
    rng = np.random.default_rng(1)
    T, N = 48, 10
    # spiky synchronized heating -> coordination should flatten it
    base = np.zeros(T)
    base[18:24] = 6.0
    base += 1.0
    h = np.tile(base, (N, 1)) * rng.uniform(0.8, 1.2, size=(N, 1))
    b = np.full((N, T), 0.5)
    uncoordinated_peak = (h.sum(axis=0) + b.sum(axis=0)).max()
    res = solve_sharing_admm(
        heating=h, background=b, alpha=0.5, rho=1.0, lam=0.05, mu=1.0,
        max_iters=500, tol=1e-6,
    )
    coordinated_peak = (res.x.sum(axis=0) + b.sum(axis=0)).max()
    assert coordinated_peak < uncoordinated_peak * 0.97


def test_non_responsive_agents_are_pinned_to_forecast():
    rng = np.random.default_rng(2)
    T, N = 24, 5
    h = np.abs(rng.normal(3.0, 0.5, size=(N, T))) + 0.5
    b = np.full((N, T), 0.4)
    forecast = h.copy()
    responsive = np.array([True, True, True, False, False])
    res = solve_sharing_admm(
        heating=h, background=b, alpha=0.5, rho=1.0, lam=0.1, mu=1.0,
        max_iters=300, tol=1e-5, responsive=responsive, forecast=forecast,
    )
    # pinned agents keep their forecast exactly
    assert np.allclose(res.x[3], forecast[3])
    assert np.allclose(res.x[4], forecast[4])
