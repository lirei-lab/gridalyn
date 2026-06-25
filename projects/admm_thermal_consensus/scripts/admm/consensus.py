"""Sharing-ADMM consensus solver for residential heating coordination.

Implements Boyd et al. (2011) sharing ADMM (§7.3) specialized to peak/variance
flattening of total feeder load with per-agent comfort, box, and daily-energy
constraints. Non-responsive agents are pinned to an externally supplied
forecast, modeling the coordinator imputing communication-failed reports.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class AdmmResult:
    """Outcome of a sharing-ADMM solve."""

    x: np.ndarray            # coordinated heating, shape (N, T)
    iterations: int
    primal_residual: float
    dual_residual: float
    converged: bool
    objective_history: list[float]


def project_capped_energy(
    q: np.ndarray, lo: np.ndarray, hi: np.ndarray, total: float
) -> np.ndarray:
    """Euclidean projection of ``q`` onto ``{lo <= x <= hi, sum(x) == total}``.

    Solves ``x = clip(q + nu, lo, hi)`` for the scalar ``nu`` making the sum
    equal ``total`` by monotone bisection (water-filling).
    """
    if total < lo.sum() - 1e-9 or total > hi.sum() + 1e-9:
        raise ValueError("infeasible energy target for the given box")

    def summed(nu: float) -> float:
        return float(np.clip(q + nu, lo, hi).sum())

    lo_nu = float((lo - q).min()) - 1.0
    hi_nu = float((hi - q).max()) + 1.0
    for _ in range(100):
        mid = 0.5 * (lo_nu + hi_nu)
        if summed(mid) < total:
            lo_nu = mid
        else:
            hi_nu = mid
        if hi_nu - lo_nu < 1e-12:
            break
    return np.clip(q + 0.5 * (lo_nu + hi_nu), lo, hi)


def solve_sharing_admm(
    *,
    heating: np.ndarray,
    background: np.ndarray,
    alpha: float,
    rho: float,
    lam: float,
    mu: float,
    max_iters: int,
    tol: float,
    responsive: np.ndarray | None = None,
    forecast: np.ndarray | None = None,
) -> AdmmResult:
    """Coordinate per-agent heating to flatten total load via sharing ADMM.

    Args:
        heating: baseline heating power, shape ``(N, T)`` (kW).
        background: fixed non-deferrable load, shape ``(N, T)`` (kW).
        alpha: deferrability fraction; box is ``[(1-alpha)h, (1+alpha)h]``.
        rho: ADMM penalty parameter.
        lam: comfort weight (deviation from baseline heating).
        mu: aggregate flattening weight.
        max_iters: iteration cap.
        tol: stop when primal+dual residual norm falls below this.
        responsive: bool array shape ``(N,)``; False agents are pinned to
            ``forecast``. Defaults to all True.
        forecast: forecast heating, shape ``(N, T)``; required if any agent is
            non-responsive.

    Returns:
        AdmmResult with coordinated heating and convergence diagnostics.
    """
    h = np.asarray(heating, dtype=float)
    b = np.asarray(background, dtype=float)
    n_agents, horizon = h.shape
    if responsive is None:
        responsive = np.ones(n_agents, dtype=bool)
    responsive = np.asarray(responsive, dtype=bool)

    lo = (1.0 - alpha) * h
    hi = (1.0 + alpha) * h
    energy = h.sum(axis=1)

    # pin non-responsive agents to a box/energy-feasible forecast
    x = h.copy()
    if not responsive.all():
        if forecast is None:
            raise ValueError("forecast required when agents are non-responsive")
        f = np.asarray(forecast, dtype=float)
        for i in np.where(~responsive)[0]:
            x[i] = project_capped_energy(f[i], lo[i], hi[i], energy[i])

    bg_total = b.sum(axis=0)                       # (T,)
    c = (energy.sum() + bg_total.sum()) / horizon  # constant flattening target

    z = x.mean(axis=0).copy()                      # (T,)
    u = np.zeros(horizon)                          # scaled dual (T,)
    active = np.where(responsive)[0]

    obj_history: list[float] = []
    primal_res = dual_res = float("inf")
    iteration = 0
    for iteration in range(1, max_iters + 1):
        xbar = x.mean(axis=0)
        # x-update for responsive agents only
        for i in active:
            center = x[i] - xbar + z - u
            q = (lam * h[i] + rho * center) / (lam + rho)
            x[i] = project_capped_energy(q, lo[i], hi[i], energy[i])
        xbar_new = x.mean(axis=0)
        # z-update (closed form): minimize (mu/2)||N z + B - c||^2 + (N rho/2)||z-u-xbar||^2
        z_new = (rho * (u + xbar_new) - mu * (bg_total - c)) / (mu * n_agents + rho)
        # u-update
        u = u + xbar_new - z_new

        primal_res = float(np.linalg.norm(xbar_new - z_new))
        dual_res = float(rho * np.linalg.norm(z_new - z))
        z = z_new

        total = x.sum(axis=0) + bg_total
        comfort = 0.5 * lam * float(((x - h) ** 2).sum())
        flat = 0.5 * mu * float(((total - c) ** 2).sum())
        obj_history.append(comfort + flat)

        if primal_res + dual_res < tol:
            break

    converged = (primal_res + dual_res) < tol
    return AdmmResult(
        x=x,
        iterations=iteration,
        primal_residual=primal_res,
        dual_residual=dual_res,
        converged=converged,
        objective_history=obj_history,
    )
