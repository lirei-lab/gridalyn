"""Solver-validation figure: sharing-ADMM objective converging to the CVXPY optimum.

Re-runs the comfort-aware sharing-ADMM on the study's ideal coordination problem,
logging the full objective (including the indoor-temperature term) at every
iteration, and overlays the centralized optimum from a CVXPY solve of the same
convex QP. Produces ``fig_convergence`` and a small JSON. Standalone (needs the
``ops`` extra for CVXPY); not part of the governed workflow.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parents[3]
sys.path.insert(0, str(ROOT))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from projects.admm_thermal_consensus.scripts import config as C
from projects.admm_thermal_consensus.scripts import comfort
from projects.admm_thermal_consensus.scripts.admm.consensus import (
    build_comfort_prox_inverse,
    project_capped_energy_batch,
    rc_response_matrix,
)


def main() -> None:
    import cvxpy as cp

    heat = pd.read_parquet(C.DATA_DIR / "agents_heating.parquet").to_numpy()
    bg = pd.read_parquet(C.DATA_DIR / "agents_background.parquet").to_numpy()
    resistance, capacitance = comfort.thermal_params()
    n, t = heat.shape
    lam, mu, rho, alpha, gamma, step_h = (
        C.ADMM_LAMBDA, C.ADMM_MU, C.ADMM_RHO, C.DEFERRABILITY_ALPHA,
        C.COMFORT_GAMMA, C.STEP_HOURS,
    )
    lo, hi = (1 - alpha) * heat, (1 + alpha) * heat
    energy = heat.sum(axis=1)
    bg_total = bg.sum(axis=0)
    c = (energy.sum() + bg_total.sum()) / t
    g_mats = [rc_response_matrix(resistance[i], capacitance[i], step_h, t) for i in range(n)]
    prox = build_comfort_prox_inverse(resistance, capacitance, step_h, t, gamma, lam, rho)

    def full_objective(x):
        comf = sum(
            0.5 * lam * np.sum((x[i] - heat[i]) ** 2)
            + 0.5 * gamma * np.sum((g_mats[i] @ (x[i] - heat[i])) ** 2)
            for i in range(n)
        )
        flat = 0.5 * mu * np.sum((x.sum(axis=0) + bg_total - c) ** 2)
        return float(comf + flat)

    # --- ADMM loop with per-iteration full-objective logging (mirrors solver) ---
    x = heat.copy()
    z = x.mean(axis=0).copy()
    u = np.zeros(t)
    history = [full_objective(x)]
    n_iters = 300
    for _ in range(n_iters):
        xbar = x.mean(axis=0)
        centers = x - xbar + (z - u)
        q = heat + rho * np.einsum("itj,ij->it", prox, centers - heat)
        x = project_capped_energy_batch(q, lo, hi, energy)
        xbar2 = x.mean(axis=0)
        xbar_or = C.ADMM_RELAX * xbar2 + (1.0 - C.ADMM_RELAX) * z
        z = (rho * (u + xbar_or) - mu * (bg_total - c)) / (mu * n + rho)
        u = u + xbar_or - z
        history.append(full_objective(x))
    history = np.asarray(history)

    # --- CVXPY centralized optimum ---
    xs = [cp.Variable(t) for _ in range(n)]
    obj = 0
    cons = []
    total = 0
    for i in range(n):
        obj += 0.5 * lam * cp.sum_squares(xs[i] - heat[i])
        obj += 0.5 * gamma * cp.sum_squares(g_mats[i] @ (xs[i] - heat[i]))
        cons += [xs[i] >= lo[i], xs[i] <= hi[i], cp.sum(xs[i]) == energy[i]]
        total = total + xs[i]
    obj += 0.5 * mu * cp.sum_squares(total + bg_total - c)
    cp.Problem(cp.Minimize(obj), cons).solve()
    opt = float(obj.value)
    gap = (history[-1] - opt) / opt

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(history, color="tab:blue", lw=2, label="Sharing-ADMM objective")
    ax.axhline(opt, ls="--", color="tab:red", label="CVXPY centralized optimum")
    ax.set_xlabel("ADMM iteration")
    ax.set_ylabel("Objective")
    ax.set_yscale("log")
    ax.legend()
    ax.grid(alpha=0.3, which="both")
    ax.set_title(f"Final relative gap: {gap * 100:.2f}%")
    C.FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    for p in (C.FIGURES_DIR / "fig_convergence.png", C.FIGURES_DIR / "fig_convergence.pdf"):
        fig.savefig(p, bbox_inches="tight", dpi=200)
    plt.close(fig)

    out = {
        "iterations_logged": n_iters,
        "admm_final_objective": float(history[-1]),
        "cvxpy_optimum": opt,
        "relative_gap": gap,
    }
    (C.JSON_DIR / "convergence_validation.json").write_text(
        json.dumps(out, indent=2), encoding="utf-8"
    )
    print(
        f"validate_convergence: ADMM {history[-1]:.2f} vs CVXPY {opt:.2f} "
        f"(gap {gap * 100:.2f}%); figure written"
    )


if __name__ == "__main__":
    main()
