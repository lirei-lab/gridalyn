import sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.datagen.grid.network import MVNetwork
from gridalyn.market.dso_dispatch import DSODispatcher
from gridalyn.datagen.data.weather import download_tmy, select_cold_day
from gridalyn.market.engine import MarketSimulationEngine
from projects.flexibility_cls.scripts.config import RES_MINUTES, S_RATED_KVA, P_LIMIT_KW, THETA_MAX

PALETTE = {
    "buildings": "#3498db",  # Blue
    "evs_managed": "#e67e22", # Orange
    "soft_cls": "#2ecc71",   # Green
    "hard_cls": "#9b59b6",   # Purple
    "thermal_limit": "#c0392b" # Red
}

def main():
    print("Generating Stage 2: Real-Time Recourse Multi-Scenario Plot...")
    
    data_dir = ROOT / "projects/flexibility_cls/outputs/data"
    out_dir = ROOT / "projects/flexibility_cls/outputs/figures/05_stage4_realtime_dispatch"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # Load stochastic data
    df_base = pd.read_parquet(data_dir / "substation_baseline_mc.parquet")
    df_ev = pd.read_parquet(data_dir / "substation_ev_capability_mc.parquet")
    
    p_base_kw_mean = df_base.mean(axis=1).values * 1000.0
    p_base_kw_std = df_base.std(axis=1).values * 1000.0
    
    # 30% EV penetration
    p_ev_kw_mean = df_ev.mean(axis=1).values * 1000.0 * (30.0 / 30.0) 
    p_ev_kw_std = df_ev.std(axis=1).values * 1000.0 * (30.0 / 30.0)
    
    tmy = download_tmy()
    cold_day = select_cold_day(tmy, duration_hours=28)
    t_out_trace = cold_day["temp_air"].resample(f"{RES_MINUTES}min").interpolate().values
    
    from gridalyn.datagen.grid.transformer_thermal import TransformerThermalModel
    thermal_model = TransformerThermalModel(theta_max=THETA_MAX, s_rated_kva=S_RATED_KVA)
    network = MVNetwork(thermal_model=thermal_model, p_rated_kw=P_LIMIT_KW)
    
    p_limit = np.zeros(len(t_out_trace))
    for t in range(len(t_out_trace)):
        p_limit[t] = thermal_model.max_load_for_temp(t_out_trace[t]) / 1000.0
        
    t_hours = np.arange(len(p_base_kw_mean)) * (RES_MINUTES / 60)
    
    # Create two-subplot layout: Unmanaged (top), Managed (bottom)
    fig, (ax_un, ax_mg) = plt.subplots(2, 1, figsize=(14, 9), sharex=True,
                                        constrained_layout=True,
                                        gridspec_kw={"height_ratios": [1, 1], "hspace": 0.08})
    
    n_realizations = len(df_base.columns)
    
    # Storage for all scenario traces
    all_unmanaged = []
    all_managed = []
    
    print(f"Running engine for {n_realizations} scenarios...")
    for idx, col_name in enumerate(df_base.columns):
        p_base_kw_realized = df_base[col_name].values * 1000.0
        p_ev_kw_realized = df_ev[col_name].values * 1000.0
        p_tot_kw_realized = p_base_kw_realized + p_ev_kw_realized
        
        dt_h = RES_MINUTES / 60.0
        dispatcher = DSODispatcher(network=network, dt_man_h=dt_h, epsilon=0.05, stochastic_failure_rate=0.05)
        market_engine = MarketSimulationEngine(network=network, dispatcher=dispatcher)
        
        df_res = market_engine.run(
            p_base_kw_mean=p_base_kw_mean,
            p_base_kw_std=p_base_kw_std,
            p_ev_kw_mean=p_ev_kw_mean,
            p_ev_kw_std=p_ev_kw_std,
            t_out_trace_c=t_out_trace,
            dt_man_h=dt_h,
            n_total_blocks=160,
            participation_rate=0.30,
            epsilon=0.05,
            is_profiled=True, market_resolution_h=0.5,
            p_tot_kw_realized=p_tot_kw_realized,
            p_ev_kw_realized=p_ev_kw_realized
        )
        
        p_soft_cls = df_res["soft_cls_kw"].values / 1000.0
        p_hard_cls = df_res["hard_cls_kw"].values / 1000.0
        
        p_unmanaged_total = p_tot_kw_realized / 1000.0
        p_managed_total = p_unmanaged_total - p_soft_cls - p_hard_cls
        
        all_unmanaged.append(p_unmanaged_total)
        all_managed.append(p_managed_total)
        
        # Top panel: Unmanaged scenarios
        ax_un.plot(t_hours, p_unmanaged_total, color='#888888', lw=0.8, ls='-', alpha=0.25)
        # Bottom panel: Managed scenarios
        ax_mg.plot(t_hours, p_managed_total, color=PALETTE["buildings"], lw=0.8, ls='-', alpha=0.3)
    
    # ----- Expected Unmanaged Load (μ) — bold reference on BOTH panels -----
    p_tot_mean = (p_base_kw_mean + p_ev_kw_mean) / 1000.0
    ax_un.plot(t_hours, p_tot_mean, color='#1a1a1a', lw=3.0, ls='-', alpha=1.0,
               label=r"Expected Unmanaged Load ($\mu$)", zorder=10)
    ax_mg.plot(t_hours, p_tot_mean, color='#1a1a1a', lw=2.0, ls=(0, (6, 2)), alpha=0.5,
               label=r"Expected Unmanaged Load ($\mu$)", zorder=5)
    
    # ----- Dynamic Thermal Limit on BOTH panels -----
    ax_un.plot(t_hours, p_limit, color=PALETTE["thermal_limit"], lw=3, ls='-',
               label=r"Dynamic Thermal Limit ($\theta_H$)", zorder=9)
    ax_mg.plot(t_hours, p_limit, color=PALETTE["thermal_limit"], lw=3, ls='-',
               label=r"Dynamic Thermal Limit ($\theta_H$)", zorder=9)
    
    # ----- Proxy legend entries for scenario spreads -----
    ax_un.plot([], [], color='#888888', lw=1.5, alpha=0.6, label="Realized Unmanaged Scenarios")
    ax_mg.plot([], [], color=PALETTE["buildings"], lw=1.5, alpha=0.8, label="Recourse Managed Scenarios (Soft+Hard CLS)")
    
    # ----- Formatting -----
    y_min = np.min(p_base_kw_mean / 1000.0) * 0.85
    y_max = 26
    for ax in (ax_un, ax_mg):
        ax.set_xlim(0, 28)
        ax.set_ylim(y_min, y_max)
        ax.set_xticks(np.arange(0, 29, 4))
        ax.set_ylabel("Substation Power\nDemand [MW]", fontsize=12)
        ax.grid(True, linestyle='--', alpha=0.4)
        ax.legend(loc="upper left", fontsize=11, framealpha=0.9)
    
    ax_un.set_title(r"Multi-Scenario Recourse Validation: Dynamic Dispatch Performance",
                    fontsize=16, weight='bold')
    ax_un.tick_params(labelbottom=False)
    
    import matplotlib.ticker as ticker
    def format_time(x, pos):
        h = int(x % 24)
        m = int(round((x % 1) * 60))
        if m == 60: h = (h + 1) % 24; m = 0
        return f"{h:02d}:{m:02d}"
    ax_mg.xaxis.set_major_formatter(ticker.FuncFormatter(format_time))
    ax_mg.set_xlabel("Time of Day [HH:MM]", fontsize=14)
    
    out_path = out_dir / "plot_16_stage_2_multiscenario.png"
    out_pdf_path = out_path.with_suffix(".pdf")
    fig.savefig(out_pdf_path, bbox_inches="tight")
    print(f"Saved PDF to {out_pdf_path}")

    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    print(f"Saved to {out_path}")
if __name__ == "__main__":
    main()
