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


def project_capped_energy_batch(
    q: np.ndarray, lo: np.ndarray, hi: np.ndarray, totals: np.ndarray
) -> np.ndarray:
    """Row-wise projection onto ``{lo<=x<=hi, sum_t x = totals}`` (vectorized).

    Equivalent to applying :func:`project_capped_energy` to each row of ``q``,
    but solves all rows' scalar duals together with a batched bisection. Rows are
    assumed feasible (``sum(lo) <= totals <= sum(hi)``), which holds here because
    the box brackets each agent's baseline and ``totals`` is its baseline energy.
    """
    lo_nu = (lo - q).min(axis=1) - 1.0
    hi_nu = (hi - q).max(axis=1) + 1.0
    for _ in range(100):
        mid = 0.5 * (lo_nu + hi_nu)
        summed = np.clip(q + mid[:, None], lo, hi).sum(axis=1)
        too_low = summed < totals
        lo_nu = np.where(too_low, mid, lo_nu)
        hi_nu = np.where(too_low, hi_nu, mid)
    nu = 0.5 * (lo_nu + hi_nu)
    return np.clip(q + nu[:, None], lo, hi)


def rc_response_matrix(
    resistance: float, capacitance: float, step_hours: float, horizon: int
) -> np.ndarray:
    """Lower-triangular map G from a heating deviation to indoor-temp deviation.

    For a first-order RC home, ``dT[k+1] = a*dT[k] + (dt/C)*Delta[k]`` with
    ``a = 1 - dt/(R*C)``; unrolling gives ``dT = G @ Delta`` where
    ``G[k,j] = (dt/C) * a**(k-1-j)`` for ``j < k``.
    """
    a = 1.0 - step_hours / (resistance * capacitance)
    g = step_hours / capacitance
    matrix = np.zeros((horizon, horizon))
    for k in range(1, horizon):
        j = np.arange(k)
        matrix[k, j] = g * a ** (k - 1 - j)
    return matrix


def build_comfort_prox_inverse(
    resistance: np.ndarray,
    capacitance: np.ndarray,
    step_hours: float,
    horizon: int,
    gamma: float,
    lam: float,
    rho: float,
) -> np.ndarray:
    """Precompute the per-agent x-update prox inverse for the comfort penalty.

    Returns ``(N, T, T)`` with row ``i`` equal to
    ``inv((lam+rho) I + gamma G_i^T G_i)``, where ``G_i`` is the home's RC
    response. With ``gamma=0`` this reduces to ``(1/(lam+rho)) I`` and the
    closed-form prox. The result is passed to :func:`solve_sharing_admm` as
    ``comfort_prox_inverse`` so the (fixed) inverse is computed once per study.
    """
    n_agents = len(resistance)
    eye = np.eye(horizon)
    inverses = np.empty((n_agents, horizon, horizon))
    for i in range(n_agents):
        g_mat = rc_response_matrix(
            float(resistance[i]), float(capacitance[i]), step_hours, horizon
        )
        inverses[i] = np.linalg.inv((lam + rho) * eye + gamma * (g_mat.T @ g_mat))
    return inverses


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
    comfort_prox_inverse: np.ndarray | None = None,
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
        comfort_prox_inverse: optional ``(N, T, T)`` array from
            :func:`build_comfort_prox_inverse`. When given, the x-update prox
            penalizes each home's modelled indoor-temperature excursion (not just
            its energy deviation), steering re-timing toward high-thermal-mass
            homes. When ``None`` the original closed-form prox is used.

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
        # x-update for responsive agents only (batched over agents)
        centers = x[active] - xbar + (z - u)
        if comfort_prox_inverse is None:
            q = (lam * h[active] + rho * centers) / (lam + rho)
        else:
            # prox of comfort + temperature penalty + ADMM penalty (closed form)
            dev = rho * np.einsum(
                "itj,ij->it", comfort_prox_inverse[active], centers - h[active]
            )
            q = h[active] + dev
        x[active] = project_capped_energy_batch(q, lo[active], hi[active], energy[active])
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
