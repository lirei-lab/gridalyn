"""Stage: compare ML estimators for non-responsive agents, with vs without imputation.

Two layers of metrics are produced:

1. Intrinsic estimation accuracy (leave-agents-out CV): RMSE, MAE, R^2 of each
   method at reconstructing an unseen home's heating profile.
2. Downstream feeder impact under the belief-vs-reality model: a silent home
   physically draws its TRUE heating, but the coordinator only has the estimate;
   it flattens the responsive homes against that estimate, and the REALIZED feeder
   aggregate (responsive coordinated + true silent + background) is mapped to the
   worst-of-day line loading. "no imputation" is the coordinator flattening the
   responsive subset blind to the silent homes.

This isolates the role of imputation: a good estimate lets the responsive homes
counter the silent peaks; without it those peaks pass through uncompensated.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.foundation.platform.capabilities import require_capabilities
from gridalyn.projects.scripting import project_script
from projects.admm_thermal_consensus.scripts import config as C
from projects.admm_thermal_consensus.scripts import comfort
from projects.admm_thermal_consensus.scripts.admm.consensus import solve_sharing_admm
from projects.admm_thermal_consensus.scripts.forecast.methods import (
    ESTIMATING_METHODS,
    fit_predict,
)
from projects.admm_thermal_consensus.scripts import lv_feeder

METHODS = (*ESTIMATING_METHODS, "none")  # add the no-imputation baseline
DISPLAY = {
    "lightgbm": "LightGBM", "random_forest": "Random forest", "ridge": "Ridge",
    "knn": "k-NN", "mean_level": "Mean-level (naive)", "none": "No imputation",
}


def _admm_responsive(heating, background, prox_subset):
    """Flatten a (responsive) subset and return its coordinated schedules."""
    res = solve_sharing_admm(
        heating=heating, background=background, alpha=C.DEFERRABILITY_ALPHA,
        rho=C.ADMM_RHO, lam=C.ADMM_LAMBDA, mu=C.ADMM_MU,
        max_iters=C.ADMM_MAX_ITERS, tol=C.ADMM_TOL,
        comfort_prox_inverse=prox_subset,
    )
    return res.x


def _realized_peak(method, heat, bg, levels, temp, silent, seed, prox):
    """Realized daily-peak (kW) for one method and one silent set."""
    bg_total = bg.sum(axis=0)
    resp = np.ones(C.N_AGENTS, dtype=bool)
    resp[silent] = False
    resp_idx = np.where(resp)[0]
    if resp_idx.size == 0:  # everyone silent -> nothing to coordinate
        return float((heat.sum(axis=0) + bg_total).max())
    if method == "none":
        # coordinator is blind to the silent homes: flatten responsives only
        sched = _admm_responsive(heat[resp_idx], bg[resp_idx], prox[resp_idx])
        realized = sched.sum(axis=0) + heat[silent].sum(axis=0) + bg_total
        return float(realized.max())
    # estimating methods: pin silent homes to the estimate, optimize responsives
    estimate = fit_predict(method, temp, heat[resp_idx], levels[resp_idx],
                           levels[silent], seed)
    forecast = heat.copy()
    forecast[silent] = estimate
    res = solve_sharing_admm(
        heating=heat, background=bg, alpha=C.DEFERRABILITY_ALPHA,
        rho=C.ADMM_RHO, lam=C.ADMM_LAMBDA, mu=C.ADMM_MU,
        max_iters=C.ADMM_MAX_ITERS, tol=C.ADMM_TOL,
        responsive=resp, forecast=forecast,
        comfort_prox_inverse=prox,
    )
    # REALITY: silent homes draw their true heating, not the estimate
    realized = res.x[resp_idx].sum(axis=0) + heat[silent].sum(axis=0) + bg_total
    return float(realized.max())


def _intrinsic_cv(heat, levels, temp):
    """5-fold leave-agents-out RMSE/MAE/R^2 per estimating method."""
    rng = np.random.default_rng(C.SEED)
    folds = np.array_split(rng.permutation(C.N_AGENTS), 5)
    out = {}
    for method in ESTIMATING_METHODS:
        per_agent_rmse, per_agent_mae, tss, rss = [], [], [], []
        for fold in folds:
            test = np.asarray(fold)
            train = np.array([i for i in range(C.N_AGENTS) if i not in set(test)])
            preds = fit_predict(method, temp, heat[train], levels[train],
                                levels[test], C.SEED)
            truth = heat[test]
            for k in range(len(test)):  # per-agent (matches train_forecaster)
                per_agent_rmse.append(float(np.sqrt(np.mean((preds[k] - truth[k]) ** 2))))
                per_agent_mae.append(float(np.mean(np.abs(preds[k] - truth[k]))))
            rss.append(((preds - truth) ** 2).sum())
            tss.append(((truth - truth.mean()) ** 2).sum())
        out[method] = {
            "rmse_kw": float(np.mean(per_agent_rmse)),
            "mae_kw": float(np.mean(per_agent_mae)),
            "r2": float(1.0 - sum(rss) / sum(tss)),
        }
    return out


def main() -> None:
    require_capabilities("sim", context="admm_thermal_consensus imputer comparison")
    script = project_script()

    heat = pd.read_parquet(C.DATA_DIR / "agents_heating.parquet").to_numpy()
    bg = pd.read_parquet(C.DATA_DIR / "agents_background.parquet").to_numpy()
    levels = heat.mean(axis=1)
    params = json.loads((C.JSON_DIR / "agent_params.json").read_text())
    temp = np.asarray(params["temperature_c"], dtype=float)

    uncoordinated_peak = float(params["uncoordinated_peak_kw"])
    peaks_kw, _vmins, loadings = lv_feeder.build_peak_curve(
        C.UQ_PEAK_GRID_N, 0.75 * uncoordinated_peak, 1.05 * uncoordinated_peak
    )

    def loading_of(peak_kw: float) -> float:
        return float(np.interp(peak_kw, peaks_kw, loadings))

    intrinsic = _intrinsic_cv(heat, levels, temp)
    prox = comfort.prox_inverse()

    # downstream: deterministic silent set per fraction, per method
    rng = np.random.default_rng(C.SEED)
    drop = rng.permutation(C.N_AGENTS)
    curves = {m: [] for m in METHODS}
    for rho_frac in C.RHO_SWEEP:
        n_down = int(round(rho_frac * C.N_AGENTS))
        silent = drop[:n_down]
        for m in METHODS:
            pk = _realized_peak(m, heat, bg, levels, temp, silent, C.SEED, prox)
            curves[m].append({"rho": rho_frac, "peak_kw": pk,
                              "loading_pct": loading_of(pk),
                              "violation": loading_of(pk) > C.LINE_LOADING_LIMIT_PCT})

    # Monte-Carlo P(violation) per method at the representative fraction
    rep = C.COMPARISON_REP_RHO
    n_down = int(round(rep * C.N_AGENTS))
    mc_rng = np.random.default_rng(C.SEED + 1)
    mc = {}
    for m in METHODS:
        peaks, loads = [], []
        for _ in range(C.COMPARISON_MC_DRAWS):
            silent = mc_rng.choice(C.N_AGENTS, size=n_down, replace=False)
            pk = _realized_peak(m, heat, bg, levels, temp, silent, C.SEED, prox)
            peaks.append(pk)
            loads.append(loading_of(pk))
        loads = np.asarray(loads)
        mc[m] = {
            "rep_rho": rep,
            "realized_peak_kw_mean": float(np.mean(peaks)),
            "realized_peak_kw_p05": float(np.percentile(peaks, 5)),
            "realized_peak_kw_p95": float(np.percentile(peaks, 95)),
            "realized_loading_pct_mean": float(loads.mean()),
            "prob_violation": float(np.mean(loads > C.LINE_LOADING_LIMIT_PCT)),
        }

    # persist
    C.DATA_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for m in METHODS:
        for rec in curves[m]:
            rows.append({"method": m, **rec})
    curve_df = pd.DataFrame(rows)
    curve_path = C.DATA_DIR / "imputer_comparison_curves.parquet"
    curve_df.to_parquet(curve_path)

    results = {
        "intrinsic_cv": intrinsic,
        "monte_carlo_rep": mc,
        "representative_rho": rep,
        "methods": list(METHODS),
        "display_names": DISPLAY,
    }
    res_path = C.JSON_DIR / "imputer_comparison.json"
    res_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    script.write_report(
        "imputer_comparison_report",
        artifacts=[script.file_reference(curve_path), script.file_reference(res_path)],
        summary={
            "methods": list(METHODS),
            "intrinsic_rmse_kw": {m: intrinsic[m]["rmse_kw"] for m in ESTIMATING_METHODS},
            "rep_rho": rep,
            "prob_violation_at_rep": {m: mc[m]["prob_violation"] for m in METHODS},
        },
    )
    best = min(ESTIMATING_METHODS, key=lambda m: intrinsic[m]["rmse_kw"])
    print(
        f"imputer_comparison: best CV RMSE = {DISPLAY[best]} "
        f"({intrinsic[best]['rmse_kw']:.3f} kW); "
        f"realized peak @ rho={rep}: "
        + ", ".join(
            f"{DISPLAY[m]} {mc[m]['realized_peak_kw_mean']:.1f}" for m in METHODS
        )
    )


if __name__ == "__main__":
    main()
