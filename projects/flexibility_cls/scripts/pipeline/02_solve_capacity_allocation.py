"""
02_solve_capacity_allocation.py

Resolves the local capacity auction (Soft CLS and Hard CLS)
Invokes MarketSimulationEngine and clears the Multi-Block Soft-CLS supply curve.
Outputs: market_dispatch_timeseries.parquet, ev_summary_results.json
"""

import sys
import json
import numpy as np
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.datagen.grid.network import MVNetwork
from gridalyn.datagen.grid.transformer_thermal import TransformerThermalModel
from gridalyn.market.dso_dispatch import DSODispatcher
from gridalyn.market.engine import MarketSimulationEngine
from projects.flexibility_cls.scripts.config import (
    EV_PERCENTAGES,
    MARKET_CLEARING_INTERVAL_H,
    N_BUILDINGS,
    N_FEEDER_BLOCKS,
    P_LIMIT_KW,
    PARTICIPATION_RATE,
    RES_MINUTES,
    S_RATED_KVA,
    THETA_MAX,
)
from projects.flexibility_cls.scripts.thermal_forecast import (
    build_thermal_forecast,
    thermal_forecast_metadata,
)

def main():
    print("="*60)
    print("  [Step 2] Solve Market Allocation (Soft/Hard CLS)")
    print("="*60)
    
    data_dir = ROOT / "projects/flexibility_cls/outputs/data"
    out_dir = ROOT / "projects/flexibility_cls/outputs/json"
    out_dir.mkdir(exist_ok=True, parents=True)
    
    b_path = data_dir / "substation_baseline_mc.parquet"
    ev_path = data_dir / "substation_ev_capability_mc.parquet"
    
    if not b_path.exists() or not ev_path.exists():
        print("[!] Parquet data not found. Please run 00_generate_stochastic_profiles.py first.")
        return
        
    df_base = pd.read_parquet(b_path)
    df_ev = pd.read_parquet(ev_path)
    
    p_base_kw_mean = df_base.mean(axis=1).values * 1000.0
    p_base_kw_std = df_base.std(axis=1).values * 1000.0
    p_base_kw_p5 = df_base.quantile(0.05, axis=1).values * 1000.0
    p_base_kw_p95 = df_base.quantile(0.95, axis=1).values * 1000.0
    
    p_ev_kw_mean = df_ev.mean(axis=1).values * 1000.0
    p_ev_kw_std = df_ev.std(axis=1).values * 1000.0
    
    res_min = RES_MINUTES
    dt_h = res_min / 60.0
    thermal_forecast = build_thermal_forecast(len(df_base.index))
    t_out_trace = thermal_forecast.ambient_c
    
    s_rated_kva = S_RATED_KVA
    p_rated_kw = P_LIMIT_KW
    
    # Initialize unified network model
    thermal_model = TransformerThermalModel(theta_max=THETA_MAX, s_rated_kva=s_rated_kva)
    network = MVNetwork(thermal_model=thermal_model, p_rated_kw=p_rated_kw)
    dispatcher = DSODispatcher(network=network, dt_man_h=dt_h, epsilon=0.05, stochastic_failure_rate=0.05)
    
    p_limit_trace_kw = np.zeros(len(t_out_trace))
    for t in range(len(t_out_trace)):
        p_limit_trace_kw[t] = thermal_model.max_load_for_temp(t_out_trace[t])
        
    summary_results = {}
    
    s2_p_ev_kw_mean = None
    s2_d_soft_cls_kw = None
    s2_d_contracted_soft_kw = None
    s2_d_hard_cls_kw = None
    s2_clearing_price = None
    
    market_engine = MarketSimulationEngine(network=network, dispatcher=dispatcher)
    
    for ev_pct in EV_PERCENTAGES:
        print(f"\n  === Scenario S{EV_PERCENTAGES.index(ev_pct)} ({ev_pct}% EV) ===")
        
        p_ev_kw_mean_sc = p_ev_kw_mean * (ev_pct / 30.0) if ev_pct > 0 else np.zeros_like(p_ev_kw_mean)
        p_ev_kw_std_sc = p_ev_kw_std * (ev_pct / 30.0) if ev_pct > 0 else np.zeros_like(p_ev_kw_std)
        n_evs_total = int(round(N_BUILDINGS * (ev_pct / 100.0)))
        
        # 30% building participation rate for a realistic Soft CLS scenario
        df_res = market_engine.run(
            p_base_kw_mean=p_base_kw_mean,
            p_base_kw_std=p_base_kw_std,
            p_ev_kw_mean=p_ev_kw_mean_sc,
            p_ev_kw_std=p_ev_kw_std_sc,
            t_out_trace_c=t_out_trace,
            dt_man_h=dt_h,
            n_total_blocks=N_FEEDER_BLOCKS,
            participation_rate=PARTICIPATION_RATE,
            epsilon=0.05,
            is_profiled=True,
            market_resolution_h=MARKET_CLEARING_INTERVAL_H
        )
        
        d_soft_cls_kw = df_res["soft_cls_kw"].values
        d_contracted_kw = df_res["contracted_soft_kw"].values
        d_hard_cls_kw = df_res["hard_cls_kw"].values
        prices = df_res["clearing_price"].values
        p_tot_kw_mean_sc = df_res["p_tot_mean_kw"].values
        managed_load_kw = df_res["managed_load_kw"].values
        market_settlement_cost = df_res["market_settlement_cost"].values
        market_penalties = df_res["market_penalties"].values
        
        total_soft_mwh = np.sum(d_soft_cls_kw) * (res_min / 60) / 1000
        total_hard_mwh = np.sum(d_hard_cls_kw) * (res_min / 60) / 1000
        total_rebound_mwh = 0.0
        if "rebound_kw" in df_res.columns:
            total_rebound_mwh = np.sum(df_res["rebound_kw"]) * (res_min / 60) / 1000
        max_price = np.max(prices) if np.max(prices) > 0 else 0
        
        total_settlement_usd = np.sum(market_settlement_cost)
        total_penalties_usd = np.sum(market_penalties)
        
        unmanaged_peak_mw = np.max(p_tot_kw_mean_sc) / 1000
        managed_peak_mw = np.max(managed_load_kw) / 1000
        
        scenario_key = f"S{EV_PERCENTAGES.index(ev_pct)}_{ev_pct}pct"
        summary_results[scenario_key] = {
            "n_ev": n_evs_total,
            "unmanaged_peak_mw": float(unmanaged_peak_mw),
            "managed_peak_mw": float(managed_peak_mw),
            "soft_cls_mw": float(np.max(d_soft_cls_kw) / 1000.0),
            "hard_cls_mw": float(np.max(d_hard_cls_kw) / 1000.0),
            "total_soft_cls_mwh": float(total_soft_mwh),
            "total_hard_cls_mwh": float(total_hard_mwh),
            "total_rebound_mwh": float(total_rebound_mwh),
            "max_auction_clearing_price": float(max_price),
            "total_market_settlement_usd": float(total_settlement_usd),
            "total_market_penalties_usd": float(total_penalties_usd)
        }
        
        print(f"      Unmanaged Peak: {unmanaged_peak_mw:.2f} MW")
        print(f"      Managed Peak:   {managed_peak_mw:.2f} MW")
        print(f"      Soft CLS:       {total_soft_mwh:.2f} MWh")
        print(f"      Hard CLS:       {total_hard_mwh:.2f} MWh")
        print(f"      Rebound:        {total_rebound_mwh:.2f} MWh")
        print(f"      Net Settlement: ${total_settlement_usd:.2f}")
        
        if ev_pct == 20:
            s2_clearing_price = max_price

        if ev_pct == 40:
            s4_p_ev_kw_mean = p_ev_kw_mean_sc.copy()
            s4_d_soft_cls_kw = d_soft_cls_kw.copy()
            s4_d_contracted_soft_kw = d_contracted_kw.copy()
            s4_d_hard_cls_kw = d_hard_cls_kw.copy()
            s4_rebound_kw = df_res["rebound_kw"].values.copy() if "rebound_kw" in df_res.columns else np.zeros_like(d_soft_cls_kw)
            s4_clearing_price = max_price

    summary_results["p_rated_mw"] = p_rated_kw / 1000.0
    s4_peak_idx = int(np.argmax(df_res["p_tot_mean_kw"].values))
    summary_results.update(
        thermal_forecast_metadata(
            thermal_forecast,
            peak_idx=s4_peak_idx,
            peak_label="s4",
        )
    )
    # Legacy alias retained for existing figures and tables.
    summary_results["p_limit_dynamic_mw"] = summary_results["dynamic_limit_max_mw"]
    summary_results["s2_clearing_price"] = float(s2_clearing_price or 0.0)
    summary_results["s4_clearing_price"] = float(s4_clearing_price)
    
    with open(out_dir / "ev_summary_results.json", "w") as f:
        json.dump(summary_results, f, indent=4)
        
    # Export S4 Dispatch array explicitly for the plotting script
    t_hours = np.arange(len(df_base.index)) * res_min / 60.0
    df_dispatch = pd.DataFrame({
        "t_hours": t_hours,
        "p_baseline_mean_mw": p_base_kw_mean / 1000.0,
        "p_baseline_p5_mw": p_base_kw_p5 / 1000.0,
        "p_baseline_p95_mw": p_base_kw_p95 / 1000.0,
        "p_ev_mean_mw": s4_p_ev_kw_mean / 1000.0,
        "p_tot_std_mw": df_res["p_tot_std_kw"].values / 1000.0 if "p_tot_std_kw" in df_res.columns else np.zeros(len(t_hours)),
        "p_soft_cls_mw": s4_d_soft_cls_kw / 1000.0,
        "p_contracted_soft_cls_mw": s4_d_contracted_soft_kw / 1000.0,
        "p_hard_cls_mw": s4_d_hard_cls_kw / 1000.0,
        "p_rebound_mw": s4_rebound_kw / 1000.0,
        "p_limit_trace_mw": p_limit_trace_kw / 1000.0,
        "p_security_mw": df_res["security_load_kw"].values / 1000.0 if "security_load_kw" in df_res.columns else np.zeros(len(t_hours)),
        "p_managed_worst_mw": df_res["managed_worst_kw"].values / 1000.0 if "managed_worst_kw" in df_res.columns else np.zeros(len(t_hours)),
    })
    
    df_dispatch.to_parquet(data_dir / "market_dispatch_timeseries.parquet", index=False)
    
    print(f"\n  -> Results dumped to {out_dir / 'ev_summary_results.json'}")
    print(f"  -> Dispatch timeseries saved to {data_dir / 'market_dispatch_timeseries.parquet'}")
    print("  ✓ Step 2 Complete\n")

if __name__ == "__main__":
    main()
