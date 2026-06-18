"""Canonical CLS replay and congestion-forecast surface.

This module unifies two formerly separate sources behind the frozen
``gridalyn.operations`` facade:

* the Stage-2 out-of-sample replay (:class:`CLSMarketReplayContext`,
  ``prepare_cls_market_replay_context``, ``summarize_stage2_realizations``),
  moved from ``gridalyn.operations.flexibility.cls_replay``;
* the probabilistic congestion forecast (:class:`CongestionForecastResult`,
  ``build_congestion_forecast``), moved from
  ``gridalyn.operations.flexibility.thermal_screening``.

CRITICAL (Pitfall 2): ``summarize_stage2_realizations`` reuses ONE shared
``DSODispatcher`` (one ``np.random.default_rng(1337)`` stream) across all
realization columns; the consumed stream depends on the
``context.baseline_mw.columns`` iteration order AND the per-timestep
``portfolios`` loop inside the engine. These draw sites are moved VERBATIM — the
dispatcher is NOT re-created per realization and no iteration order is changed —
so every ``*.Eomega.*`` baseline number is reproduced bit-for-bit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd
from scipy.stats import norm

from gridalyn.assets.datagen.grid.network import MVNetwork
from gridalyn.assets.modeling.thermal import (
    ThermalForecast,
    thermal_forecast_metadata,
)
from gridalyn.assets.modeling.transformers import TransformerThermalModel
from gridalyn.operations.clearing.engine_mode import (
    DSODispatcher,
    MarketSimulationEngine,
)


@dataclass(frozen=True)
class CLSMarketReplayContext:
    """Prepared CLS market inputs for one EV-adoption replay scenario."""

    baseline_mw: pd.DataFrame
    ev_capability_mw: pd.DataFrame
    ev_percent: float
    ev_capability_reference_percent: float
    resolution_minutes: int
    n_feeder_blocks: int
    participation_rate: float
    epsilon: float
    market_resolution_h: float
    non_delivery_penalty: float
    min_aggregator_cost: float
    max_aggregator_cost: float
    pay_full_block: bool
    p_base_kw_mean: np.ndarray
    p_base_kw_std: np.ndarray
    p_ev_kw_mean: np.ndarray
    p_ev_kw_std: np.ndarray
    t_out_trace_c: np.ndarray
    p_limit_mw: np.ndarray
    t_hours: np.ndarray
    thermal_model: TransformerThermalModel
    network: MVNetwork
    dispatcher: DSODispatcher
    market_engine: MarketSimulationEngine

    @property
    def dt_h(self) -> float:
        """Return the market timestep in hours."""
        return float(self.resolution_minutes) / 60.0

    @property
    def n_steps(self) -> int:
        """Return the number of profile timesteps."""
        return int(len(self.p_base_kw_mean))

    def run(
        self,
        *,
        is_profiled: bool = True,
        p_tot_kw_realized: np.ndarray | None = None,
        p_ev_kw_realized: np.ndarray | None = None,
    ) -> pd.DataFrame:
        """Run the market engine using the prepared replay inputs."""
        return self.market_engine.run(
            p_base_kw_mean=self.p_base_kw_mean,
            p_base_kw_std=self.p_base_kw_std,
            p_ev_kw_mean=self.p_ev_kw_mean,
            p_ev_kw_std=self.p_ev_kw_std,
            t_out_trace_c=self.t_out_trace_c,
            dt_man_h=self.dt_h,
            n_total_blocks=self.n_feeder_blocks,
            participation_rate=self.participation_rate,
            epsilon=self.epsilon,
            is_profiled=is_profiled,
            market_resolution_h=self.market_resolution_h,
            p_tot_kw_realized=p_tot_kw_realized,
            p_ev_kw_realized=p_ev_kw_realized,
            non_delivery_penalty=self.non_delivery_penalty,
            min_aggregator_cost=self.min_aggregator_cost,
            max_aggregator_cost=self.max_aggregator_cost,
            pay_full_block=self.pay_full_block,
        )

    def realization_traces(self, column: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return baseline, EV, and total realized kW traces for one MC column."""
        if column not in self.baseline_mw or column not in self.ev_capability_mw:
            raise KeyError(f"Missing realization column: {column}")
        p_base_kw = self.baseline_mw[column].values * 1000.0
        p_ev_kw = self.ev_capability_mw[column].values * 1000.0 * self.ev_scale
        return p_base_kw, p_ev_kw, p_base_kw + p_ev_kw

    @property
    def ev_scale(self) -> float:
        """Return the EV-capability scaling factor for this scenario."""
        return _ev_scale(self.ev_percent, self.ev_capability_reference_percent)


def prepare_cls_market_replay_context(
    *,
    baseline_mw: pd.DataFrame,
    ev_capability_mw: pd.DataFrame,
    thermal_forecast: ThermalForecast,
    ev_percent: float,
    resolution_minutes: int,
    s_rated_kva: float,
    p_limit_kw: float,
    theta_max: float,
    n_feeder_blocks: int,
    participation_rate: float,
    ev_capability_reference_percent: float = 30.0,
    epsilon: float = 0.05,
    stochastic_failure_rate: float = 0.05,
    market_resolution_h: float = 0.5,
    hard_cls_price: float = 10.0,
    non_delivery_penalty: float = 10.0,
    min_aggregator_cost: float = 3.0,
    max_aggregator_cost: float = 8.0,
    pay_full_block: bool = False,
) -> CLSMarketReplayContext:
    """Prepare reusable CLS replay inputs from Monte Carlo profile tables."""
    if baseline_mw.empty or ev_capability_mw.empty:
        raise ValueError("baseline_mw and ev_capability_mw must contain traces.")
    if baseline_mw.shape != ev_capability_mw.shape:
        raise ValueError("baseline_mw and ev_capability_mw must have the same shape.")
    if len(thermal_forecast.ambient_c) < len(baseline_mw):
        raise ValueError("thermal_forecast must cover the baseline profile horizon.")

    scale = _ev_scale(ev_percent, ev_capability_reference_percent)
    p_base_kw_mean = baseline_mw.mean(axis=1).values * 1000.0
    p_base_kw_std = baseline_mw.std(axis=1).values * 1000.0
    p_ev_kw_mean = ev_capability_mw.mean(axis=1).values * 1000.0 * scale
    p_ev_kw_std = ev_capability_mw.std(axis=1).values * 1000.0 * scale
    t_out_trace_c = np.asarray(thermal_forecast.ambient_c, dtype=float)[: len(baseline_mw)]

    thermal_model = TransformerThermalModel(theta_max=theta_max, s_rated_kva=s_rated_kva)
    network = MVNetwork(thermal_model=thermal_model, p_rated_kw=p_limit_kw)
    dispatcher = DSODispatcher(
        network=network,
        dt_man_h=float(resolution_minutes) / 60.0,
        epsilon=epsilon,
        stochastic_failure_rate=stochastic_failure_rate,
        hard_cls_price=hard_cls_price,
    )
    market_engine = MarketSimulationEngine(network=network, dispatcher=dispatcher)

    return CLSMarketReplayContext(
        baseline_mw=baseline_mw,
        ev_capability_mw=ev_capability_mw,
        ev_percent=float(ev_percent),
        ev_capability_reference_percent=float(ev_capability_reference_percent),
        resolution_minutes=int(resolution_minutes),
        n_feeder_blocks=int(n_feeder_blocks),
        participation_rate=float(participation_rate),
        epsilon=float(epsilon),
        market_resolution_h=float(market_resolution_h),
        non_delivery_penalty=float(non_delivery_penalty),
        min_aggregator_cost=float(min_aggregator_cost),
        max_aggregator_cost=float(max_aggregator_cost),
        pay_full_block=bool(pay_full_block),
        p_base_kw_mean=p_base_kw_mean,
        p_base_kw_std=p_base_kw_std,
        p_ev_kw_mean=p_ev_kw_mean,
        p_ev_kw_std=p_ev_kw_std,
        t_out_trace_c=t_out_trace_c,
        p_limit_mw=np.asarray(thermal_forecast.p_limit_kw, dtype=float)[: len(baseline_mw)] / 1000.0,
        t_hours=np.arange(len(baseline_mw)) * float(resolution_minutes) / 60.0,
        thermal_model=thermal_model,
        network=network,
        dispatcher=dispatcher,
        market_engine=market_engine,
    )


def summarize_stage2_realizations(
    context: CLSMarketReplayContext,
    *,
    is_profiled: bool = True,
) -> dict[str, object]:
    """Replay the real-time stage against every Monte Carlo realization.

    This is the out-of-sample counterpart of the security-envelope dispatch:
    each realization column is fed to the engine as the metered load, and the
    distribution of Soft/Hard CLS energy and settlement across realizations
    approximates the expectation over scenarios in the two-stage formulation.

    The shared ``context.dispatcher`` / ``context.market_engine`` (one
    ``np.random.default_rng(1337)`` stream) is reused across every realization
    column in ``context.baseline_mw.columns`` order — this draw site is moved
    verbatim and must not be reordered or re-created (Pitfall 2).
    """
    dt_h = context.dt_h
    soft_mwh: list[float] = []
    hard_mwh: list[float] = []
    settlement_usd: list[float] = []
    penalties_usd: list[float] = []
    for column in context.baseline_mw.columns:
        _, p_ev_kw, p_tot_kw = context.realization_traces(column)
        frame = context.run(
            is_profiled=is_profiled,
            p_tot_kw_realized=p_tot_kw,
            p_ev_kw_realized=p_ev_kw,
        )
        soft_mwh.append(float(frame["soft_cls_kw"].sum() * dt_h / 1000.0))
        hard_mwh.append(float(frame["hard_cls_kw"].sum() * dt_h / 1000.0))
        settlement_usd.append(float(frame["market_settlement_cost"].sum()))
        penalties_usd.append(float(frame["market_penalties"].sum()))

    soft = np.asarray(soft_mwh)
    hard = np.asarray(hard_mwh)
    total = soft + hard
    hard_share = np.where(total > 0, hard / np.maximum(total, 1e-12), 0.0)

    def _stats(values: np.ndarray) -> dict[str, float]:
        return {
            "mean": float(values.mean()),
            "p5": float(np.percentile(values, 5)),
            "p50": float(np.percentile(values, 50)),
            "p95": float(np.percentile(values, 95)),
        }

    return {
        "n_realizations": int(len(soft)),
        "soft_cls_mwh": _stats(soft),
        "hard_cls_mwh": _stats(hard),
        "hard_share": _stats(hard_share),
        "settlement_usd": _stats(np.asarray(settlement_usd)),
        "penalties_usd": _stats(np.asarray(penalties_usd)),
        "realizations_with_hard_cls": int(np.sum(hard > 0.01)),
    }


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


def _ev_scale(ev_percent: float, reference_percent: float) -> float:
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


__all__ = [
    "CLSMarketReplayContext",
    "CongestionForecastResult",
    "build_congestion_forecast",
    "prepare_cls_market_replay_context",
    "summarize_stage2_realizations",
]
