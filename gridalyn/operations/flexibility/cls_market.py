"""CLS market-study utilities for EV adoption scenario sweeps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import pandas as pd

from gridalyn.assets.datagen.grid.network import MVNetwork
from gridalyn.assets.modeling.thermal import (
    ThermalForecast,
    thermal_forecast_metadata,
)
from gridalyn.assets.modeling.transformers import TransformerThermalModel
from gridalyn.operations.market.dso_dispatch import DSODispatcher
from gridalyn.operations.market.engine import MarketSimulationEngine


@dataclass(frozen=True)
class CLSCapacityAllocationResult:
    """Scenario-sweep output for CLS market allocation."""

    summary: dict[str, object]
    dispatch_timeseries: pd.DataFrame


def run_cls_capacity_allocation(
    *,
    baseline_mw: pd.DataFrame,
    ev_capability_mw: pd.DataFrame,
    ev_percentages: Sequence[int],
    thermal_forecast: ThermalForecast,
    n_buildings: int,
    n_feeder_blocks: int,
    participation_rate: float,
    resolution_minutes: int,
    s_rated_kva: float,
    p_limit_kw: float,
    theta_max: float,
    market_clearing_interval_h: float,
    dispatch_ev_percent: int = 40,
    reference_price_ev_percent: int = 20,
    ev_capability_reference_percent: float = 30.0,
    epsilon: float = 0.05,
    stochastic_failure_rate: float = 0.05,
    hard_cls_price: float = 10.0,
    non_delivery_penalty: float = 10.0,
    min_aggregator_cost: float = 3.0,
    max_aggregator_cost: float = 8.0,
    pay_full_block: bool = False,
) -> CLSCapacityAllocationResult:
    """Run a Soft/Hard CLS market allocation over declared EV scenarios."""

    if baseline_mw.empty or ev_capability_mw.empty:
        raise ValueError("baseline_mw and ev_capability_mw must contain traces.")
    if baseline_mw.shape != ev_capability_mw.shape:
        raise ValueError(
            "baseline_mw and ev_capability_mw must have the same shape."
        )
    if dispatch_ev_percent not in ev_percentages:
        raise ValueError("dispatch_ev_percent must be one of ev_percentages.")

    p_base_kw_mean = baseline_mw.mean(axis=1).values * 1000.0
    p_base_kw_std = baseline_mw.std(axis=1).values * 1000.0
    p_base_kw_p5 = baseline_mw.quantile(0.05, axis=1).values * 1000.0
    p_base_kw_p95 = baseline_mw.quantile(0.95, axis=1).values * 1000.0

    p_ev_kw_mean = ev_capability_mw.mean(axis=1).values * 1000.0
    p_ev_kw_std = ev_capability_mw.std(axis=1).values * 1000.0

    dt_h = resolution_minutes / 60.0
    t_out_trace = np.asarray(thermal_forecast.ambient_c, dtype=float)
    thermal_model = TransformerThermalModel(
        theta_max=theta_max,
        s_rated_kva=s_rated_kva,
    )
    network = MVNetwork(thermal_model=thermal_model, p_rated_kw=p_limit_kw)
    dispatcher = DSODispatcher(
        network=network,
        dt_man_h=dt_h,
        epsilon=epsilon,
        stochastic_failure_rate=stochastic_failure_rate,
        hard_cls_price=hard_cls_price,
    )
    market_engine = MarketSimulationEngine(network=network, dispatcher=dispatcher)
    p_limit_trace_kw = np.array(
        [thermal_model.max_load_for_temp(temp_c) for temp_c in t_out_trace],
        dtype=float,
    )

    summary_results: dict[str, object] = {}
    reference_clearing_price = None
    dispatch_payload: dict[str, np.ndarray] | None = None
    dispatch_df_res: pd.DataFrame | None = None

    for scenario_index, ev_pct in enumerate(ev_percentages):
        scale = _ev_scale(ev_pct, ev_capability_reference_percent)
        p_ev_kw_mean_sc = p_ev_kw_mean * scale if ev_pct > 0 else np.zeros_like(p_ev_kw_mean)
        p_ev_kw_std_sc = p_ev_kw_std * scale if ev_pct > 0 else np.zeros_like(p_ev_kw_std)
        n_evs_total = int(round(n_buildings * (float(ev_pct) / 100.0)))

        df_res = market_engine.run(
            p_base_kw_mean=p_base_kw_mean,
            p_base_kw_std=p_base_kw_std,
            p_ev_kw_mean=p_ev_kw_mean_sc,
            p_ev_kw_std=p_ev_kw_std_sc,
            t_out_trace_c=t_out_trace,
            dt_man_h=dt_h,
            n_total_blocks=n_feeder_blocks,
            participation_rate=participation_rate,
            epsilon=epsilon,
            is_profiled=True,
            market_resolution_h=market_clearing_interval_h,
            non_delivery_penalty=non_delivery_penalty,
            min_aggregator_cost=min_aggregator_cost,
            max_aggregator_cost=max_aggregator_cost,
            pay_full_block=pay_full_block,
        )

        d_soft_cls_kw = df_res["soft_cls_kw"].values
        d_contracted_kw = df_res["contracted_soft_kw"].values
        d_hard_cls_kw = df_res["hard_cls_kw"].values
        prices = df_res["clearing_price"].values
        p_tot_kw_mean_sc = df_res["p_tot_mean_kw"].values
        managed_load_kw = df_res["managed_load_kw"].values
        market_settlement_cost = df_res["market_settlement_cost"].values
        market_penalties = df_res["market_penalties"].values
        rebound_kw = (
            df_res["rebound_kw"].values
            if "rebound_kw" in df_res.columns
            else np.zeros_like(d_soft_cls_kw)
        )

        max_price = float(np.max(prices)) if np.max(prices) > 0 else 0.0
        scenario_key = scenario_label(scenario_index, ev_pct)
        summary_results[scenario_key] = {
            "n_ev": n_evs_total,
            "unmanaged_peak_mw": float(np.max(p_tot_kw_mean_sc) / 1000.0),
            "managed_peak_mw": float(np.max(managed_load_kw) / 1000.0),
            "soft_cls_mw": float(np.max(d_soft_cls_kw) / 1000.0),
            "hard_cls_mw": float(np.max(d_hard_cls_kw) / 1000.0),
            "total_soft_cls_mwh": float(np.sum(d_soft_cls_kw) * dt_h / 1000.0),
            "total_hard_cls_mwh": float(np.sum(d_hard_cls_kw) * dt_h / 1000.0),
            "total_rebound_mwh": float(np.sum(rebound_kw) * dt_h / 1000.0),
            "max_auction_clearing_price": max_price,
            "total_market_settlement_usd": float(np.sum(market_settlement_cost)),
            "total_market_penalties_usd": float(np.sum(market_penalties)),
        }

        if ev_pct == reference_price_ev_percent:
            reference_clearing_price = max_price
        if ev_pct == dispatch_ev_percent:
            dispatch_df_res = df_res
            dispatch_payload = {
                "p_ev_mean_mw": p_ev_kw_mean_sc / 1000.0,
                "p_soft_cls_mw": d_soft_cls_kw / 1000.0,
                "p_contracted_soft_cls_mw": d_contracted_kw / 1000.0,
                "p_hard_cls_mw": d_hard_cls_kw / 1000.0,
                "p_rebound_mw": rebound_kw / 1000.0,
            }
            dispatch_clearing_price = max_price

    if dispatch_payload is None or dispatch_df_res is None:
        raise ValueError("No dispatch scenario was generated.")

    summary_results["p_rated_mw"] = p_limit_kw / 1000.0
    peak_idx = int(np.argmax(dispatch_df_res["p_tot_mean_kw"].values))
    peak_label = "s4" if dispatch_ev_percent == 40 else f"s{dispatch_ev_percent}"
    summary_results.update(
        thermal_forecast_metadata(
            thermal_forecast,
            peak_idx=peak_idx,
            peak_label=peak_label,
        )
    )
    summary_results["p_limit_dynamic_mw"] = summary_results["dynamic_limit_max_mw"]
    summary_results[f"s{reference_price_ev_percent}_clearing_price"] = float(
        reference_clearing_price or 0.0
    )
    summary_results[f"s{dispatch_ev_percent}_clearing_price"] = float(
        dispatch_clearing_price
    )
    if reference_price_ev_percent == 20:
        summary_results["s2_clearing_price"] = float(reference_clearing_price or 0.0)
    if dispatch_ev_percent == 40:
        summary_results["s4_clearing_price"] = float(dispatch_clearing_price)

    t_hours = np.arange(len(baseline_mw.index)) * resolution_minutes / 60.0
    dispatch_timeseries = pd.DataFrame(
        {
            "t_hours": t_hours,
            "p_baseline_mean_mw": p_base_kw_mean / 1000.0,
            "p_baseline_p5_mw": p_base_kw_p5 / 1000.0,
            "p_baseline_p95_mw": p_base_kw_p95 / 1000.0,
            "p_ev_mean_mw": dispatch_payload["p_ev_mean_mw"],
            "p_tot_std_mw": _column_or_zeros(dispatch_df_res, "p_tot_std_kw", len(t_hours)) / 1000.0,
            "p_soft_cls_mw": dispatch_payload["p_soft_cls_mw"],
            "p_contracted_soft_cls_mw": dispatch_payload["p_contracted_soft_cls_mw"],
            "p_hard_cls_mw": dispatch_payload["p_hard_cls_mw"],
            "p_rebound_mw": dispatch_payload["p_rebound_mw"],
            "p_limit_trace_mw": p_limit_trace_kw / 1000.0,
            "p_security_mw": _column_or_zeros(dispatch_df_res, "security_load_kw", len(t_hours)) / 1000.0,
            "p_managed_worst_mw": _column_or_zeros(dispatch_df_res, "managed_worst_kw", len(t_hours)) / 1000.0,
        }
    )
    return CLSCapacityAllocationResult(
        summary=summary_results,
        dispatch_timeseries=dispatch_timeseries,
    )


def scenario_label(index: int, ev_percent: int) -> str:
    """Return the canonical EV scenario label used by study reports."""
    return f"S{int(index)}_{int(ev_percent)}pct"


def _ev_scale(ev_percent: int, reference_percent: float) -> float:
    return float(ev_percent) / float(reference_percent) if ev_percent > 0 else 0.0


def _column_or_zeros(frame: pd.DataFrame, column: str, length: int) -> np.ndarray:
    if column not in frame.columns:
        return np.zeros(length)
    return frame[column].values


__all__ = [
    "CLSCapacityAllocationResult",
    "run_cls_capacity_allocation",
    "scenario_label",
]
