import sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from pathlib import Path

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.datagen.grid.network import MVNetwork
from gridalyn.market.dso_dispatch import DSODispatcher
from gridalyn.datagen.data.weather import download_tmy, select_cold_day
from gridalyn.market.engine import MarketSimulationEngine
from projects.flexibility_cls.scripts.config import RES_MINUTES, S_RATED_KVA, P_LIMIT_KW, THETA_MAX

def main():
    print("Generating Aggregator Limitation Contract Trajectory...")
    
    data_dir = ROOT / "projects/flexibility_cls/outputs/data"
    out_dir = ROOT / "projects/flexibility_cls/outputs/figures/05_stage4_realtime_dispatch"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Load stochastic data
    df_base = pd.read_parquet(data_dir / "substation_baseline_mc.parquet")
    df_ev = pd.read_parquet(data_dir / "substation_ev_capability_mc.parquet")
    
    p_base_kw_mean = df_base.mean(axis=1).values * 1000.0
    p_base_kw_std = df_base.std(axis=1).values * 1000.0
    
    p_ev_kw_mean = df_ev.mean(axis=1).values * 1000.0
    p_ev_kw_std = df_ev.std(axis=1).values * 1000.0
    
    tmy = download_tmy()
    cold_day = select_cold_day(tmy, duration_hours=28)
    t_out_trace = cold_day["temp_air"].resample(f"{RES_MINUTES}min").interpolate().values
    
    # Initialize components
    from gridalyn.datagen.grid.transformer_thermal import TransformerThermalModel
    thermal_model = TransformerThermalModel(theta_max=THETA_MAX, s_rated_kva=S_RATED_KVA)
    network = MVNetwork(thermal_model=thermal_model, p_rated_kw=P_LIMIT_KW)
    dt_h = RES_MINUTES / 60.0
    dispatcher = DSODispatcher(network=network, dt_man_h=dt_h, epsilon=0.05, stochastic_failure_rate=0.05)
    market_engine = MarketSimulationEngine(network=network, dispatcher=dispatcher)
    
    N_TOTAL_BLOCKS = 160
    MARKET_RES_H = 0.5  # 30-min clearing periods
    
    # Single run: Soft-CLS Firm DA Contract (sub-period clearing)
    df_res = market_engine.run(
        p_base_kw_mean=p_base_kw_mean, p_base_kw_std=p_base_kw_std,
        p_ev_kw_mean=p_ev_kw_mean, p_ev_kw_std=p_ev_kw_std,
        t_out_trace_c=t_out_trace, dt_man_h=dt_h, n_total_blocks=N_TOTAL_BLOCKS,
        participation_rate=0.30, epsilon=0.05, is_profiled=True,
        market_resolution_h=MARKET_RES_H         
    )
    
    n_steps = len(p_base_kw_mean)
    t_hours = np.arange(n_steps) * dt_h
    
    block_id = 0
    alloc_kw = df_res[f"alloc_{block_id}"].values       # curtailment per step (kW)
    deficit_kwh = df_res[f"deficit_{block_id}"].values    # continuous thermal deficit
    cost_per_kw = df_res[f"marginal_cost_{block_id}"].values
    
    # ---- Aggregator traces ----
    # P_baseline: time-varying demand — what the building NEEDS at each timestep
    p_baseline_kw = p_base_kw_mean / N_TOTAL_BLOCKS
    # P_nominal: installed heating capacity — from the digital twin (MC simulation)
    # Use the p99 peak across all 30 MC scenarios to represent the block's
    # physical installed capacity (the system was dimensioned for worst-case cold).
    # On the coldest design day, the building operates very near P_nominal (LF=0.86).
    p_block_peaks = (df_base.max(axis=0).values * 1000.0) / N_TOTAL_BLOCKS
    p_nominal_kw = float(np.percentile(p_block_peaks, 99))  # ~120 kW
    
    # ---- Discretize the limitation contract to 30-min clearing steps ----
    steps_per_period = int(round(MARKET_RES_H / dt_h))
    alloc_discrete = np.zeros(n_steps)
    p_limit_contract = p_baseline_kw.copy()
    target_trace = df_res["target_deficit_kw"].values
    for i in range(0, n_steps, steps_per_period):
        end = min(i + steps_per_period, n_steps)
        period_alloc = float(np.max(alloc_kw[i:end]))
        alloc_discrete[i:end] = period_alloc
        if period_alloc > 0.01:
            period_targets = target_trace[i:end]
            ref_idx = i + int(np.argmax(period_targets)) if np.max(period_targets) > 0 else i
            p_limit_contract[i:end] = p_baseline_kw[ref_idx] - period_alloc
    
    # The limitation contract is an absolute cap held constant over the
    # 30-minute market block. Outside the congestion window the contract is not
    # active, so P_limit = P_baseline.
    congestion_mask = alloc_discrete > 0.01
    
    # ---- FIX 3: Marginal cost should = base_cost when deficit=0 ----
    # The engine records the offer price which includes ToU multiplier even without deficit.
    # For visualization, the "realized cost" is only meaningful when deficit > 0.
    # Clamp to base_cost when deficit is negligible.
    base_cost = cost_per_kw[0]  # first timestep has no deficit → this IS the base cost
    cost_corrected = np.where(deficit_kwh > 0.01, cost_per_kw, base_cost)
    
    # ---- PLOTTING ----
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    
    # HH:MM time formatter
    def format_time(x, pos):
        h = int(x % 24)
        m = int(round((x % 1) * 60))
        if m == 60: h = (h + 1) % 24; m = 0
        return f"{h:02d}:{m:02d}"
    
    # ==== Subplot 1: Limitation Contract ====
    # P_nominal: INSTALLED HEATING CAPACITY — horizontal reference
    axes[0].axhline(y=p_nominal_kw, color='#2c3e50', lw=2.0, ls='-.',
                    label=rf"$P_{{nominal}}$ = {p_nominal_kw:.0f} kW (Installed Capacity)")
    
    # P_baseline: time-varying demand (what the building needs)
    axes[0].plot(t_hours, p_baseline_kw, color='#2c3e50', lw=1.5, ls='--',
                 label=r"$P_{baseline}$ (Heating Demand)")
    
    # Discrete limitation contract (only visible during congestion window)
    p_limit_visible = np.where(congestion_mask, p_limit_contract, np.nan)
    axes[0].step(t_hours, p_limit_visible, where='post', color='#c0392b', lw=2.5,
                 label=r"$P_{limit}$ (DA Contracted Cap, 30-min steps)")
    
    # Shade the actual curtailment: only where P_limit < P_baseline
    # Deficit = ∫(P_baseline - P_limit)⁺ dt — only when the contract is below demand
    curtail_power = np.maximum(p_baseline_kw - p_limit_contract, 0)
    axes[0].fill_between(t_hours, p_limit_contract, p_baseline_kw,
                         where=curtail_power > 0,
                         step='post', color='#e74c3c', alpha=0.25,
                         label=r"Firm Curtailment $\Delta P = P_{base} - P_{limit}$")
    
    axes[0].set_ylabel("Power\n[kW]", fontsize=12)
    # No title — caption managed by LaTeX
    axes[0].grid(True, linestyle='--', alpha=0.5)
    axes[0].legend(loc="lower left", fontsize=10)
    
    # ==== Subplot 2: Deficit (integral of curtailment) + Marginal Cost (dual axis) ====
    ax2_left = axes[1]
    ax2_left.plot(t_hours, deficit_kwh, color='#e67e22', lw=2,
                  label=r"Accumulated Deficit $\int P_{curtail}\,dt$ [kWh]")
    ax2_left.fill_between(t_hours, 0, deficit_kwh, color='#e67e22', alpha=0.12)
    ax2_left.set_ylabel("Accumulated\nDeficit [kWh]", fontsize=12, color='#e67e22')
    ax2_left.tick_params(axis='y', labelcolor='#e67e22')
    ax2_left.grid(True, linestyle='--', alpha=0.5)
    
    ax2_right = ax2_left.twinx()
    ax2_right.plot(t_hours, cost_corrected, color='#8e44ad', lw=2, ls='--',
                   label="Marginal Discomfort Cost [$/kW-h]")
    ax2_right.set_ylabel("Marginal Cost\n[$/kW-h]", fontsize=12, color='#8e44ad')
    ax2_right.tick_params(axis='y', labelcolor='#8e44ad')

    # Combined legend
    lines1, labels1 = ax2_left.get_legend_handles_labels()
    lines2, labels2 = ax2_right.get_legend_handles_labels()
    ax2_left.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=10)

    # Shared X axis: extend to 04:00 (28h)
    axes[1].set_xlim(0, 28)
    axes[1].set_xticks(np.arange(0, 29, 4))
    axes[1].xaxis.set_major_formatter(ticker.FuncFormatter(format_time))
    axes[1].set_xlabel("Time of Day [HH:MM]", fontsize=12)

    plt.tight_layout()

    out_path = out_dir / "plot_17_aggregator_trajectory.png"
    out_pdf_path = out_path.with_suffix(".pdf")
    fig.savefig(out_pdf_path, bbox_inches="tight")
    print(f"Saved PDF to {out_pdf_path}")

    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    print(f"Saved to {out_path}")

if __name__ == "__main__":
    main()
