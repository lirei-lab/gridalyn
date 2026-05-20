import sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.assets.datagen.grid.network import MVNetwork
from gridalyn.operations.market.dso_dispatch import DSODispatcher
from gridalyn.assets.datagen.data.weather import download_tmy, select_cold_day
from gridalyn.operations.market.engine import MarketSimulationEngine
from projects.flexibility_cls.scripts.config import RES_MINUTES, S_RATED_KVA, P_LIMIT_KW, THETA_MAX

PALETTE = {
    "buildings": "#3498db",  # Blue
    "evs_mean": "#e67e22",   # Orange
    "evs_worst": "#d35400",  # Darker orange
    "soft_cls_contract": "#27ae60", # Dark Green
    "hard_cls_expected": "#8e44ad", # Purple
    "thermal_limit": "#c0392b" # Red
}

def main():
    print("Generating Stage 1: Day-Ahead Dimensioning Plot...")
    
    data_dir = ROOT / "projects/flexibility_cls/outputs/data"
    out_dir = ROOT / "projects/flexibility_cls/outputs/figures/04_stage3_market_clearing"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Load stochastic data
    df_base = pd.read_parquet(data_dir / "substation_baseline_mc.parquet")
    df_ev = pd.read_parquet(data_dir / "substation_ev_capability_mc.parquet")
    
    p_base_kw_mean = df_base.mean(axis=1).values * 1000.0
    p_base_kw_std = df_base.std(axis=1).values * 1000.0
    
    # 40% EV penetration
    p_ev_kw_mean = df_ev.mean(axis=1).values * 1000.0 * (40.0 / 30.0) 
    p_ev_kw_std = df_ev.std(axis=1).values * 1000.0 * (40.0 / 30.0)
    
    tmy = download_tmy()
    cold_day = select_cold_day(tmy, duration_hours=28)
    t_out_trace = cold_day["temp_air"].resample(f"{RES_MINUTES}min").interpolate().values
    
    # Initialize components
    from gridalyn.assets.datagen.grid.transformer_thermal import TransformerThermalModel
    thermal_model = TransformerThermalModel(theta_max=THETA_MAX, s_rated_kva=S_RATED_KVA)
    network = MVNetwork(thermal_model=thermal_model, p_rated_kw=P_LIMIT_KW)
    dt_h = RES_MINUTES / 60.0
    dispatcher = DSODispatcher(network=network, dt_man_h=dt_h, epsilon=0.05, stochastic_failure_rate=0.05)
    market_engine = MarketSimulationEngine(network=network, dispatcher=dispatcher)
    
    # Run the engine (Standard statistical mode to get contracts)
    df_res = market_engine.run(
        p_base_kw_mean=p_base_kw_mean,
        p_base_kw_std=p_base_kw_std,
        p_ev_kw_mean=p_ev_kw_mean,
        p_ev_kw_std=p_ev_kw_std,
        t_out_trace_c=t_out_trace,
        dt_man_h=dt_h,
        n_total_blocks=160,
        participation_rate=0.30, # 30% aggregator participation
        epsilon=0.05,            # 95% Confidence
        is_profiled=False, market_resolution_h=0.5         # Window-level capacity option
    )
    
    t_hours = np.arange(len(p_base_kw_mean)) * (RES_MINUTES / 60)
    
    p_tot_mean = df_res["p_tot_mean_kw"].values / 1000.0
    p_tot_std = df_res["p_tot_std_kw"].values / 1000.0
    
    p_limit = np.zeros(len(t_out_trace))
    for t in range(len(t_out_trace)):
        p_limit[t] = thermal_model.max_load_for_temp(t_out_trace[t]) / 1000.0
        
    contracted_soft_mw = df_res["contracted_soft_kw"].values / 1000.0
    expected_hard_mw = df_res["hard_cls_kw"].values / 1000.0
    
    from scipy.stats import norm
    z_score = norm.ppf(1 - 0.05)
    p_worst = p_tot_mean + z_score * p_tot_std
    
    # Create plot
    fig, ax = plt.subplots(figsize=(14, 7))
    
    # Plot expected unmanaged load
    ax.plot(t_hours, p_tot_mean, color='black', lw=2, label=r"Expected Unmanaged Load ($\mu$)")
    
    # Plot worst case
    ax.plot(t_hours, p_worst, color=PALETTE["evs_worst"], lw=2, ls='--', label=r"95th Pct. Worst-Case Envelope ($\mu + Z \cdot \sigma$)")
    ax.fill_between(t_hours, p_tot_mean, p_worst, color=PALETTE["evs_worst"], alpha=0.2, hatch='//')
    
    # Dynamic Limit
    ax.plot(t_hours, p_limit, color=PALETTE["thermal_limit"], lw=3, ls='-', label=r"Dynamic Thermal Limit ($\theta_H$)")
    
    # Expected Activations for visualization
    expected_soft_act_mw = np.minimum(contracted_soft_mw, np.maximum(0, p_worst - p_limit))
    expected_hard_act_mw = np.maximum(0, p_worst - p_limit - expected_soft_act_mw)

    # Plot Soft-CLS Expected Activation
    ax.fill_between(t_hours, p_worst - expected_soft_act_mw, p_worst, where=(expected_soft_act_mw > 0),
                    color=PALETTE["soft_cls_contract"], alpha=0.8, label="Soft-CLS: Firm Contracted Capacity")
    soft_cls_patch = None

    # Plot Hard-CLS Expected Activation
    ax.fill_between(t_hours, p_worst - expected_soft_act_mw - expected_hard_act_mw, p_worst - expected_soft_act_mw, where=(expected_hard_act_mw > 0),
                    color=PALETTE["hard_cls_expected"], alpha=0.6, label="Hard-CLS: Expected Interruptible Recourse")

    # Plot Expected Rebound — directly from the engine (already thermally clamped)
    p_rebound_mw = df_res["rebound_kw"].values / 1000.0

    if np.max(p_rebound_mw) > 0:
        ax.fill_between(t_hours, p_tot_mean, p_tot_mean + p_rebound_mw,
                        where=(p_rebound_mw > 0.001),
                        color="#D9534F", alpha=0.8, hatch='\\\\', label="Expected Post-Congestion Rebound")

    
    # Formatting
    ax.set_ylabel("Substation Power Demand [MW]", fontsize=14)
    
    ax.set_title("First-Stage Stochastic Programming: Day-Ahead Capacity Option", fontsize=18, weight='bold')
    
    ax.set_xlim(0, 28)
    ax.set_ylim(np.min(p_tot_mean) * 0.8, np.max(p_worst) * 1.1)
    
    ax.set_xticks(np.arange(0, 29, 4))

    # Elegant Time Formatting (HH:MM) starting from offset 12:00
    import matplotlib.ticker as ticker
    def format_time(x, pos):
        h = int(x % 24)
        m = int(round((x % 1) * 60))
        if m == 60: h = (h + 1) % 24; m = 0
        return f"{h:02d}:{m:02d}"
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(format_time))
    ax.set_xlabel("Time of Day [HH:MM]", fontsize=14)

    
    ax.grid(True, linestyle='--', alpha=0.4)
    
    handles, labels = ax.get_legend_handles_labels()
    if soft_cls_patch is not None:
        handles.insert(3, soft_cls_patch)  # Insert after thermal limit roughly
        labels.insert(3, soft_cls_patch.get_label())
        
    ax.legend(handles=handles, labels=labels, loc="upper left", fontsize=12, framealpha=0.9)
    
    plt.tight_layout()
    
    out_path = out_dir / "plot_14_stage_1_day_ahead.png"
    out_pdf_path = out_path.with_suffix(".pdf")
    fig.savefig(out_pdf_path, bbox_inches="tight")
    print(f"Saved PDF to {out_pdf_path}")

    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    print(f"Saved to {out_path}")
if __name__ == "__main__":
    main()
