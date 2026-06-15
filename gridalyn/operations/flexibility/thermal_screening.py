"""Thermal screening utilities for flexibility studies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd
from scipy.stats import norm

from gridalyn.assets.modeling.thermal import (
    ThermalForecast,
    thermal_forecast_metadata,
)


@dataclass(frozen=True)
class CongestionForecastResult:
    """Probabilistic congestion-screening outputs for a scenario sweep."""

    requirements: dict[str, object]
    temporal_bounds: pd.DataFrame
    base_peak_values_mw: np.ndarray
    target_peak_values_mw: np.ndarray


def build_congestion_forecast(
    *,
    baseline_mw: pd.DataFrame,
    ev_capability_mw: pd.DataFrame,
    ev_percentages: Sequence[int],
    p_rated_kw: float,
    resolution_minutes: int,
    thermal_forecast: ThermalForecast,
    target_ev_percent: int = 20,
    ev_capability_reference_percent: float = 30.0,
    risk_quantile: float = 1.645,
) -> CongestionForecastResult:
    """Build thermal requirements and temporal bounds from Monte Carlo traces."""

    if baseline_mw.empty or ev_capability_mw.empty:
        raise ValueError("baseline_mw and ev_capability_mw must contain traces.")
    if baseline_mw.shape != ev_capability_mw.shape:
        raise ValueError(
            "baseline_mw and ev_capability_mw must have the same shape."
        )
    if len(thermal_forecast.p_limit_kw) != len(baseline_mw):
        raise ValueError(
            "thermal_forecast length must match the number of profile timesteps."
        )
    if target_ev_percent not in ev_percentages:
        raise ValueError("target_ev_percent must be one of ev_percentages.")

    n_realizations = baseline_mw.shape[1]
    n_steps = baseline_mw.shape[0]
    t_hours = np.arange(n_steps) * resolution_minutes / 60.0
    p_limit_trace_kw = np.asarray(thermal_forecast.p_limit_kw, dtype=float)
    t_out_trace = np.asarray(thermal_forecast.ambient_c, dtype=float)
    thermal_model = thermal_forecast.model

    base_traces_mw = baseline_mw.values.T
    ev_traces_mw = ev_capability_mw.values.T
    base_mean_kw = baseline_mw.mean(axis=1).values * 1000.0
    base_std_kw = baseline_mw.std(axis=1).values * 1000.0
    ev_mean_kw = ev_capability_mw.mean(axis=1).values * 1000.0
    ev_std_kw = ev_capability_mw.std(axis=1).values * 1000.0

    prob_limit: list[float] = []
    prob_rated: list[float] = []
    medians: list[float] = []
    p5s: list[float] = []
    p95s: list[float] = []
    scenario_traces_mw: dict[int, np.ndarray] = {}

    for pct in ev_percentages:
        scale = _ev_scale(pct, ev_capability_reference_percent)
        traces_mw = base_traces_mw + ev_traces_mw * scale
        scenario_traces_mw[int(pct)] = traces_mw

        peaks_kw = traces_mw.max(axis=1) * 1000.0
        mean_kw = base_mean_kw + ev_mean_kw * scale
        std_kw = np.sqrt(base_std_kw**2 + (ev_std_kw * scale) ** 2)
        exceed_prob_trace = 1.0 - norm.cdf(p_limit_trace_kw, loc=mean_kw, scale=std_kw)

        prob_limit.append(float(np.max(exceed_prob_trace)))
        prob_rated.append(float(np.mean(peaks_kw > p_rated_kw)))
        medians.append(float(np.median(peaks_kw)))
        p5s.append(float(np.percentile(peaks_kw, 5)))
        p95s.append(float(np.percentile(peaks_kw, 95)))

    target_traces_mw = scenario_traces_mw[target_ev_percent]
    target_median = np.median(target_traces_mw, axis=0)
    peak_idx = int(np.argmax(target_median))
    target_peak_values_mw = target_traces_mw[:, peak_idx]

    target_scale = _ev_scale(target_ev_percent, ev_capability_reference_percent)
    p_mean_trace_kw = base_mean_kw + ev_mean_kw * target_scale
    p_std_trace_kw = np.sqrt(base_std_kw**2 + (ev_std_kw * target_scale) ** 2)
    p_worst_trace_kw = p_mean_trace_kw + risk_quantile * p_std_trace_kw
    probabilistic_relief_kw = np.maximum(0.0, p_worst_trace_kw - p_limit_trace_kw)
    d_optimal_kw = _thermal_relief_target_kw(
        p_worst_trace_kw=p_worst_trace_kw,
        p_limit_trace_kw=p_limit_trace_kw,
        t_out_trace=t_out_trace,
        resolution_minutes=resolution_minutes,
        thermal_forecast=thermal_forecast,
    )

    limit_at_peak_mw = float(p_limit_trace_kw[peak_idx] / 1000.0)
    requirements: dict[str, object] = {
        "ev_pct_list": list(ev_percentages),
        "prob_limit": prob_limit,
        "prob_rated": prob_rated,
        "medians_kw": medians,
        "p5s_kw": p5s,
        "p95s_kw": p95s,
        "p_limit_kw": float(limit_at_peak_mw * 1000.0),
        "p_rated_kw": float(p_rated_kw),
        "D_tar_mw": float(np.max(probabilistic_relief_kw) / 1000.0),
        "thermal_bisection_D_tar_mw": float(d_optimal_kw / 1000.0),
        "limit_at_peak_mw": limit_at_peak_mw,
        "frac_pos_overload": float(
            np.mean(target_peak_values_mw > limit_at_peak_mw) * 100.0
        ),
        "mu_peak": float(np.mean(target_peak_values_mw)),
        "std_peak": float(np.std(target_peak_values_mw)),
        "mu_base": float(np.mean(base_traces_mw[:, peak_idx])),
        "std_base": float(np.std(base_traces_mw[:, peak_idx])),
        "peak_hour": float(t_hours[peak_idx]),
        "n_realizations": int(n_realizations),
    }
    requirements.update(
        thermal_forecast_metadata(
            thermal_forecast,
            peak_idx=peak_idx,
            peak_label="diagnostic",
        )
    )
    requirements["dynamic_limit_at_peak_mw"] = limit_at_peak_mw

    temporal_bounds = pd.DataFrame(
        {
            "t_hours": t_hours,
            "p_limit_trace": p_limit_trace_kw / 1000.0,
            "base_p5": np.percentile(base_traces_mw, 5, axis=0),
            "base_median": np.median(base_traces_mw, axis=0),
            "base_p95": np.percentile(base_traces_mw, 95, axis=0),
            "s2_p5": np.percentile(target_traces_mw, 5, axis=0),
            "s2_median": target_median,
            "s2_p95": np.percentile(target_traces_mw, 95, axis=0),
        }
    )

    return CongestionForecastResult(
        requirements=requirements,
        temporal_bounds=temporal_bounds,
        base_peak_values_mw=base_traces_mw[:, peak_idx],
        target_peak_values_mw=target_peak_values_mw,
    )


def _ev_scale(ev_percent: int, reference_percent: float) -> float:
    return float(ev_percent) / float(reference_percent) if ev_percent > 0 else 0.0


def _thermal_relief_target_kw(
    *,
    p_worst_trace_kw: np.ndarray,
    p_limit_trace_kw: np.ndarray,
    t_out_trace: np.ndarray,
    resolution_minutes: int,
    thermal_forecast: ThermalForecast,
) -> float:
    d_hi_kw = float(np.max(np.maximum(0.0, p_worst_trace_kw - p_limit_trace_kw)))
    if d_hi_kw <= 0:
        return 0.0

    thermal_model = thermal_forecast.model
    theta_base = thermal_model.simulate_profile(
        p_worst_trace_kw,
        t_out_trace,
        dt_min=float(resolution_minutes),
    )
    if np.max(theta_base) <= thermal_model.theta_max:
        return 0.0

    d_lo_kw = 0.0
    d_optimal_kw = d_hi_kw
    for _ in range(15):
        d_mid_kw = (d_lo_kw + d_hi_kw) / 2.0
        p_test_kw = np.maximum(0.0, p_worst_trace_kw - d_mid_kw)
        theta_test = thermal_model.simulate_profile(
            p_test_kw,
            t_out_trace,
            dt_min=float(resolution_minutes),
        )
        if np.max(theta_test) <= thermal_model.theta_max:
            d_hi_kw = d_mid_kw
            d_optimal_kw = d_mid_kw
        else:
            d_lo_kw = d_mid_kw
    return float(d_optimal_kw)


__all__ = ["CongestionForecastResult", "build_congestion_forecast"]
