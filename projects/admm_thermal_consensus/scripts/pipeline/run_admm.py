"""Stage: run sharing-ADMM across scenarios and the comms-failure sweep."""

from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.projects.scripting import project_script
from projects.admm_thermal_consensus.scripts import config as C
from projects.admm_thermal_consensus.scripts.admm.consensus import solve_sharing_admm


def _kpis(total_kw: np.ndarray, price_per_step: np.ndarray) -> dict[str, float]:
    peak = float(total_kw.max())
    mean = float(total_kw.mean())
    return {
        "peak_kw": peak,
        "mean_kw": mean,
        "par": peak / mean if mean else 0.0,
        "energy_cost_cad": float((total_kw * price_per_step * C.STEP_HOURS).sum()),
    }


def main() -> None:
    script = project_script()
    heat = pd.read_parquet(C.DATA_DIR / "agents_heating.parquet").to_numpy()
    bg = pd.read_parquet(C.DATA_DIR / "agents_background.parquet").to_numpy()
    bg_total = bg.sum(axis=0)
    levels = heat.mean(axis=1)
    params = json.loads((C.JSON_DIR / "agent_params.json").read_text())
    temp = np.asarray(params["temperature_c"], dtype=float)
    with open(C.CACHE_DIR / "imputer.pkl", "rb") as fh:
        imputer = pickle.load(fh)

    # per-step TOU price expanded from hourly
    hourly = np.asarray(C.tou_price_per_hour(), dtype=float)
    steps_per_hour = 60 // C.RESOLUTION_MINUTES
    price_per_step = np.repeat(hourly, steps_per_hour)[: C.N_STEPS]

    profiles: dict[str, np.ndarray] = {}
    kpis: dict[str, dict] = {}
    convergence: dict[str, dict] = {}

    # 1) uncoordinated
    total_unc = heat.sum(axis=0) + bg_total
    profiles["uncoordinated"] = total_unc
    kpis["uncoordinated"] = _kpis(total_unc, price_per_step)

    # 2) coordinated ideal
    res = solve_sharing_admm(
        heating=heat, background=bg, alpha=C.DEFERRABILITY_ALPHA,
        rho=C.ADMM_RHO, lam=C.ADMM_LAMBDA, mu=C.ADMM_MU,
        max_iters=C.ADMM_MAX_ITERS, tol=C.ADMM_TOL,
    )
    total_ideal = res.x.sum(axis=0) + bg_total
    profiles["coordinated_ideal"] = total_ideal
    kpis["coordinated_ideal"] = _kpis(total_ideal, price_per_step)
    kpis["coordinated_ideal"]["comfort_mae_kw"] = float(np.abs(res.x - heat).mean())
    convergence["coordinated_ideal"] = {
        "iterations": res.iterations,
        "primal_residual": res.primal_residual,
        "dual_residual": res.dual_residual,
        "converged": res.converged,
    }

    # 3) coordinated + imputation sweep
    rng = np.random.default_rng(C.SEED)
    drop_order = rng.permutation(C.N_AGENTS)
    forecast = np.vstack([imputer.predict_agent(temp, float(levels[i])) for i in range(C.N_AGENTS)])
    for rho_frac in C.RHO_SWEEP:
        n_down = int(round(rho_frac * C.N_AGENTS))
        responsive = np.ones(C.N_AGENTS, dtype=bool)
        responsive[drop_order[:n_down]] = False
        res = solve_sharing_admm(
            heating=heat, background=bg, alpha=C.DEFERRABILITY_ALPHA,
            rho=C.ADMM_RHO, lam=C.ADMM_LAMBDA, mu=C.ADMM_MU,
            max_iters=C.ADMM_MAX_ITERS, tol=C.ADMM_TOL,
            responsive=responsive, forecast=forecast,
        )
        total = res.x.sum(axis=0) + bg_total
        key = f"imputed_rho_{int(round(rho_frac * 100)):03d}"
        profiles[key] = total
        k = _kpis(total, price_per_step)
        k["non_responsive_fraction"] = rho_frac
        k["n_non_responsive"] = n_down
        # imputation error on the down agents only
        down = drop_order[:n_down]
        if n_down:
            k["imputation_rmse_kw"] = float(
                np.sqrt(np.mean((forecast[down] - heat[down]) ** 2))
            )
        else:
            k["imputation_rmse_kw"] = 0.0
        kpis[key] = k
        convergence[key] = {
            "iterations": res.iterations,
            "primal_residual": res.primal_residual,
            "dual_residual": res.dual_residual,
            "converged": res.converged,
        }

    # persist
    C.DATA_DIR.mkdir(parents=True, exist_ok=True)
    agg_df = pd.DataFrame(profiles)
    agg_path = C.DATA_DIR / "aggregate_profiles.parquet"
    agg_df.to_parquet(agg_path)
    kpis_path = C.JSON_DIR / "aggregate_kpis.json"
    conv_path = C.JSON_DIR / "admm_convergence.json"
    kpis_path.write_text(json.dumps(kpis, indent=2), encoding="utf-8")
    conv_path.write_text(json.dumps(convergence, indent=2), encoding="utf-8")

    peak_reduction = (
        1 - kpis["coordinated_ideal"]["peak_kw"] / kpis["uncoordinated"]["peak_kw"]
    )
    script.write_report(
        "admm_report",
        artifacts=[
            script.file_reference(agg_path),
            script.file_reference(kpis_path),
            script.file_reference(conv_path),
        ],
        summary={
            "uncoordinated_peak_kw": kpis["uncoordinated"]["peak_kw"],
            "coordinated_ideal_peak_kw": kpis["coordinated_ideal"]["peak_kw"],
            "ideal_peak_reduction_fraction": float(peak_reduction),
            "ideal_par": kpis["coordinated_ideal"]["par"],
            "uncoordinated_par": kpis["uncoordinated"]["par"],
            "rho_sweep": list(C.RHO_SWEEP),
        },
    )
    print(f"run_admm: ideal peak reduction {peak_reduction * 100:.1f}%")


if __name__ == "__main__":
    main()
