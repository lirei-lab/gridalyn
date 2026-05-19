"""
01_congestion_forecast.py

Generates the probabilistic congestion forecast from the same Monte Carlo
profiles used by the paper results. Static nameplate exceedance and dynamic
IEEE C57.91 thermal-limit exceedance are reported separately.
Outputs: flex_requirements.json, congestion_temporal_bounds.parquet.
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from projects.flexibility_cls.scripts.config import (
    EV_PERCENTAGES,
    N_REALIZATIONS,
    P_RATED_KW,
    RES_MINUTES,
)
from projects.flexibility_cls.scripts.thermal_forecast import (
    build_thermal_forecast,
    thermal_forecast_metadata,
)

DATA_DIR = ROOT / "projects/flexibility_cls/outputs/data"
OUTPUTS_DIR = ROOT / "projects/flexibility_cls/outputs/json"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


def _load_mc_profiles() -> tuple[pd.DataFrame, pd.DataFrame]:
    b_path = DATA_DIR / "substation_baseline_mc.parquet"
    ev_path = DATA_DIR / "substation_ev_capability_mc.parquet"

    if not b_path.exists() or not ev_path.exists():
        raise FileNotFoundError(
            "Parquet data not found. Run 00_generate_stochastic_profiles.py first."
        )

    return pd.read_parquet(b_path), pd.read_parquet(ev_path)


def main():
    print("=" * 60)
    print("  [Step 1] Congestion Forecast & Target Calculation")
    print("=" * 60)

    df_baseline, df_ev = _load_mc_profiles()
    n_realizations = df_baseline.shape[1]
    if n_realizations != N_REALIZATIONS:
        print(
            f"  [!] Expected {N_REALIZATIONS} MC realizations from config, "
            f"found {n_realizations} in parquet."
        )

    n_steps = df_baseline.shape[0]
    t_hours = np.arange(n_steps) * RES_MINUTES / 60.0
    thermal_forecast = build_thermal_forecast(n_steps)
    t_out_trace = thermal_forecast.ambient_c
    p_limit_trace_kw = thermal_forecast.p_limit_kw
    thermal_model = thermal_forecast.model

    base_traces_mw = df_baseline.values.T
    ev_traces_mw = df_ev.values.T
    base_mean_kw = df_baseline.mean(axis=1).values * 1000.0
    base_std_kw = df_baseline.std(axis=1).values * 1000.0
    ev_mean_kw = df_ev.mean(axis=1).values * 1000.0
    ev_std_kw = df_ev.std(axis=1).values * 1000.0

    prob_limit, prob_rated = [], []
    medians, p5s, p95s = [], [], []
    scenario_traces_mw: dict[int, np.ndarray] = {}

    for pct in EV_PERCENTAGES:
        scale = pct / 30.0 if pct > 0 else 0.0
        traces_mw = base_traces_mw + ev_traces_mw * scale
        scenario_traces_mw[pct] = traces_mw

        peaks_kw = traces_mw.max(axis=1) * 1000.0
        mean_kw = base_mean_kw + ev_mean_kw * scale
        std_kw = np.sqrt(base_std_kw**2 + (ev_std_kw * scale) ** 2)
        exceed_prob_trace = 1.0 - norm.cdf(p_limit_trace_kw, loc=mean_kw, scale=std_kw)

        prob_limit.append(float(np.max(exceed_prob_trace)))
        prob_rated.append(float(np.mean(peaks_kw > P_RATED_KW)))
        medians.append(float(np.median(peaks_kw)))
        p5s.append(float(np.percentile(peaks_kw, 5)))
        p95s.append(float(np.percentile(peaks_kw, 95)))

    # The paper discusses the preventive Soft-CLS regime at S2. The temporal
    # bounds and D_tar diagnostic therefore remain anchored to 20% EV.
    s2_traces_mw = scenario_traces_mw[20]
    p_median = np.median(s2_traces_mw, axis=0)
    peak_idx = int(np.argmax(p_median))
    peak_vals_mw = s2_traces_mw[:, peak_idx]

    s2_scale = 20.0 / 30.0
    p_mean_trace_kw = base_mean_kw + ev_mean_kw * s2_scale
    p_std_trace_kw = np.sqrt(base_std_kw**2 + (ev_std_kw * s2_scale) ** 2)
    p_worst_trace_kw = p_mean_trace_kw + 1.645 * p_std_trace_kw
    probabilistic_relief_kw = np.maximum(0.0, p_worst_trace_kw - p_limit_trace_kw)

    d_lo_kw = 0.0
    d_hi_kw = float(np.max(np.maximum(0.0, p_worst_trace_kw - p_limit_trace_kw)))
    d_optimal_kw = d_hi_kw
    if d_hi_kw > 0:
        theta_base = thermal_model.simulate_profile(
            p_worst_trace_kw, t_out_trace, dt_min=float(RES_MINUTES)
        )
        if np.max(theta_base) <= thermal_model.theta_max:
            d_optimal_kw = 0.0
        else:
            for _ in range(15):
                d_mid_kw = (d_lo_kw + d_hi_kw) / 2.0
                p_test_kw = np.maximum(0.0, p_worst_trace_kw - d_mid_kw)
                theta_test = thermal_model.simulate_profile(
                    p_test_kw, t_out_trace, dt_min=float(RES_MINUTES)
                )
                if np.max(theta_test) <= thermal_model.theta_max:
                    d_hi_kw = d_mid_kw
                    d_optimal_kw = d_mid_kw
                else:
                    d_lo_kw = d_mid_kw

    limit_at_peak_mw = float(p_limit_trace_kw[peak_idx] / 1000.0)
    dynamic_design_limit_kw = float(limit_at_peak_mw * 1000.0)

    exceedance_results = {
        "ev_pct_list": EV_PERCENTAGES,
        "prob_limit": prob_limit,
        "prob_rated": prob_rated,
        "medians_kw": medians,
        "p5s_kw": p5s,
        "p95s_kw": p95s,
        "p_limit_kw": dynamic_design_limit_kw,
        "p_rated_kw": float(P_RATED_KW),
        "D_tar_mw": float(np.max(probabilistic_relief_kw) / 1000.0),
        "thermal_bisection_D_tar_mw": float(d_optimal_kw / 1000.0),
        "limit_at_peak_mw": limit_at_peak_mw,
        "frac_pos_overload": float(np.mean(peak_vals_mw > limit_at_peak_mw) * 100.0),
        "mu_peak": float(np.mean(peak_vals_mw)),
        "std_peak": float(np.std(peak_vals_mw)),
        "mu_base": float(np.mean(base_traces_mw[:, peak_idx])),
        "std_base": float(np.std(base_traces_mw[:, peak_idx])),
        "peak_hour": float(t_hours[peak_idx]),
        "n_realizations": int(n_realizations),
    }
    exceedance_results.update(
        thermal_forecast_metadata(
            thermal_forecast,
            peak_idx=peak_idx,
            peak_label="diagnostic",
        )
    )
    exceedance_results["dynamic_limit_at_peak_mw"] = limit_at_peak_mw

    np.save(DATA_DIR / "base_peak_vals.npy", base_traces_mw[:, peak_idx])
    np.save(DATA_DIR / "s2_peak_vals.npy", peak_vals_mw)

    with open(OUTPUTS_DIR / "flex_requirements.json", "w") as f:
        json.dump(exceedance_results, f, indent=4)

    df_temporal = pd.DataFrame(
        {
            "t_hours": t_hours,
            "p_limit_trace": p_limit_trace_kw / 1000.0,
            "base_p5": np.percentile(base_traces_mw, 5, axis=0),
            "base_median": np.median(base_traces_mw, axis=0),
            "base_p95": np.percentile(base_traces_mw, 95, axis=0),
            "s2_p5": np.percentile(s2_traces_mw, 5, axis=0),
            "s2_median": p_median,
            "s2_p95": np.percentile(s2_traces_mw, 95, axis=0),
        }
    )
    df_temporal.to_parquet(DATA_DIR / "congestion_temporal_bounds.parquet", index=False)

    print(f"  -> Saved dynamic thermal bounds to {OUTPUTS_DIR / 'flex_requirements.json'}")
    print(f"  -> Saved temporal trace limits to {DATA_DIR / 'congestion_temporal_bounds.parquet'}")
    print("  ✓ Step 1 Complete\n")


if __name__ == "__main__":
    main()
