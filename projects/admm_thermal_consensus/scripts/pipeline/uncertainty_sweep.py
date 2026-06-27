"""Stage: Monte-Carlo forecast-uncertainty sweep over the non-responsive fraction.

For each non-responsive fraction varrho we draw ``UQ_N_DRAWS`` random failing
subsets and perturb their imputed heating by Gaussian forecast residuals (std =
the imputer's cross-validated RMSE), re-run sharing-ADMM, and record the daily
aggregate peak. Because the feeder injection is the aggregate distributed by
fixed bus weights and scaled, the worst-of-day minimum voltage and maximum line
loading are deterministic, monotone functions of the daily peak (MW); they are
read from a peak->(vmin, loading) curve precomputed with a handful of power
flows rather than re-solving the full day for every draw.

Outputs per varrho: mean and a [P5, P95] band for peak, worst min voltage, and
worst max line loading, plus the probability of a thermal line violation
P(loading > 100%).
"""

from __future__ import annotations

import json
import math
import pickle
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
from projects.admm_thermal_consensus.scripts import lv_feeder


def main() -> None:
    require_capabilities("sim", context="admm_thermal_consensus uncertainty sweep")
    script = project_script()

    heat = pd.read_parquet(C.DATA_DIR / "agents_heating.parquet").to_numpy()
    bg = pd.read_parquet(C.DATA_DIR / "agents_background.parquet").to_numpy()
    bg_total = bg.sum(axis=0)
    levels = heat.mean(axis=1)
    params = json.loads((C.JSON_DIR / "agent_params.json").read_text())
    temp = np.asarray(params["temperature_c"], dtype=float)
    cv = json.loads((C.JSON_DIR / "forecast_cv.json").read_text())
    sigma = float(cv["cv_rmse_kw_mean"])  # forecast residual std

    with open(C.CACHE_DIR / "imputer.pkl", "rb") as fh:
        imputer = pickle.load(fh)
    forecast = np.vstack(
        [imputer.predict_agent(temp, float(levels[i])) for i in range(C.N_AGENTS)]
    )

    uncoordinated_peak = float(params["uncoordinated_peak_kw"])
    peaks_kw, vmins, loadings = lv_feeder.build_peak_curve(
        C.UQ_PEAK_GRID_N, 0.75 * uncoordinated_peak, 1.05 * uncoordinated_peak
    )

    def map_peak_kw(peak_kw: float) -> tuple[float, float]:
        return (
            float(np.interp(peak_kw, peaks_kw, vmins)),
            float(np.interp(peak_kw, peaks_kw, loadings)),
        )

    prox = comfort.prox_inverse()
    rng = np.random.default_rng(C.SEED)
    records = []
    per_draw = []
    for rho_frac in C.RHO_SWEEP:
        n_down = int(round(rho_frac * C.N_AGENTS))
        draws = 1 if n_down == 0 else C.UQ_N_DRAWS
        peak_kw = np.zeros(draws)
        vmin_arr = np.zeros(draws)
        load_arr = np.zeros(draws)
        for d in range(draws):
            responsive = np.ones(C.N_AGENTS, dtype=bool)
            down = rng.choice(C.N_AGENTS, size=n_down, replace=False)
            responsive[down] = False
            fc = forecast.copy()
            if n_down:
                noise = rng.normal(0.0, sigma, size=(n_down, C.N_STEPS))
                fc[down] = np.maximum(0.0, forecast[down] + noise)
            res = solve_sharing_admm(
                heating=heat, background=bg, alpha=C.DEFERRABILITY_ALPHA,
                rho=C.ADMM_RHO, lam=C.ADMM_LAMBDA, mu=C.ADMM_MU, relax=C.ADMM_RELAX,
                max_iters=C.ADMM_MAX_ITERS, tol=C.ADMM_TOL,
                responsive=responsive, forecast=fc,
                comfort_prox_inverse=prox,
            )
            total = res.x.sum(axis=0) + bg_total
            pk = float(total.max())
            vmn, ld = map_peak_kw(pk)
            peak_kw[d], vmin_arr[d], load_arr[d] = pk, vmn, ld
            per_draw.append(
                {"rho": rho_frac, "draw": d, "peak_kw": pk,
                 "min_voltage_pu": vmn, "line_loading_pct": ld}
            )

        records.append(
            {
                "non_responsive_fraction": rho_frac,
                "n_non_responsive": n_down,
                "n_draws": draws,
                "peak_kw_mean": float(peak_kw.mean()),
                "peak_kw_p05": float(np.percentile(peak_kw, C.UQ_BAND_LOW_PCT)),
                "peak_kw_p95": float(np.percentile(peak_kw, C.UQ_BAND_HIGH_PCT)),
                "min_voltage_pu_mean": float(vmin_arr.mean()),
                "min_voltage_pu_p05": float(np.percentile(vmin_arr, C.UQ_BAND_LOW_PCT)),
                "min_voltage_pu_p95": float(np.percentile(vmin_arr, C.UQ_BAND_HIGH_PCT)),
                "line_loading_pct_mean": float(load_arr.mean()),
                "line_loading_pct_p05": float(np.percentile(load_arr, C.UQ_BAND_LOW_PCT)),
                "line_loading_pct_p95": float(np.percentile(load_arr, C.UQ_BAND_HIGH_PCT)),
                "prob_line_violation": float(
                    np.mean(load_arr > C.LINE_LOADING_LIMIT_PCT)
                ),
            }
        )

    summary_df = pd.DataFrame(records)
    draws_df = pd.DataFrame(per_draw)
    C.DATA_DIR.mkdir(parents=True, exist_ok=True)
    summary_path = C.DATA_DIR / "uncertainty_summary.parquet"
    draws_path = C.DATA_DIR / "uncertainty_draws.parquet"
    summary_df.to_parquet(summary_path)
    draws_df.to_parquet(draws_path)

    # validation: the precomputed curve must reproduce the deterministic points
    val_vmin, val_load = map_peak_kw(float(params["uncoordinated_peak_kw"]))
    curve_check = {
        "uncoordinated_peak_kw": float(params["uncoordinated_peak_kw"]),
        "curve_vmin_at_uncoordinated": val_vmin,
        "curve_loading_at_uncoordinated": val_load,
    }
    uq_path = C.JSON_DIR / "uncertainty_results.json"
    uq_path.write_text(
        json.dumps(
            {
                "forecast_residual_std_kw": sigma,
                "n_draws": C.UQ_N_DRAWS,
                "band": [C.UQ_BAND_LOW_PCT, C.UQ_BAND_HIGH_PCT],
                "by_fraction": records,
                "curve_check": curve_check,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    script.write_report(
        "uncertainty_report",
        artifacts=[
            script.file_reference(summary_path),
            script.file_reference(draws_path),
            script.file_reference(uq_path),
        ],
        summary={
            "n_draws": C.UQ_N_DRAWS,
            "forecast_residual_std_kw": sigma,
            "prob_line_violation_by_fraction": {
                str(r["non_responsive_fraction"]): r["prob_line_violation"]
                for r in records
            },
        },
    )
    msg = ", ".join(
        f"varrho={r['non_responsive_fraction']}: P(viol)={r['prob_line_violation']:.2f}"
        for r in records
    )
    print(f"uncertainty_sweep: {msg}")


if __name__ == "__main__":
    main()
