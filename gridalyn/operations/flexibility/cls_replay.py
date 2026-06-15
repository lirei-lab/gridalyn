"""Replay helpers for CLS market visualizations and diagnostics."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from gridalyn.assets.datagen.grid.network import MVNetwork
from gridalyn.assets.modeling.thermal import ThermalForecast
from gridalyn.assets.modeling.transformers import TransformerThermalModel
from gridalyn.operations.market.dso_dispatch import DSODispatcher
from gridalyn.operations.market.engine import MarketSimulationEngine


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
        return float(self.resolution_minutes) / 60.0

    @property
    def n_steps(self) -> int:
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


def _ev_scale(ev_percent: float, reference_percent: float) -> float:
    return float(ev_percent) / float(reference_percent) if ev_percent > 0 else 0.0


__all__ = [
    "CLSMarketReplayContext",
    "prepare_cls_market_replay_context",
    "summarize_stage2_realizations",
]
