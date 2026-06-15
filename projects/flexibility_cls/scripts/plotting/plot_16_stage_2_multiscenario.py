import sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.interfaces import apply_hour_axis, save_figure_pair, style_timeseries_axis
from gridalyn.operations.flexibility import prepare_cls_market_replay_context
from projects.flexibility_cls.scripts.config import RES_MINUTES, S_RATED_KVA, P_LIMIT_KW, THETA_MAX
from projects.flexibility_cls.scripts.thermal_forecast import build_thermal_forecast

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
    
    context = prepare_cls_market_replay_context(
        baseline_mw=df_base,
        ev_capability_mw=df_ev,
        thermal_forecast=build_thermal_forecast(len(df_base.index)),
        ev_percent=30.0,
        resolution_minutes=RES_MINUTES,
        s_rated_kva=S_RATED_KVA,
        p_limit_kw=P_LIMIT_KW,
        theta_max=THETA_MAX,
        n_feeder_blocks=160,
        participation_rate=0.30,
        market_resolution_h=0.5,
    )
    p_base_kw_mean = context.p_base_kw_mean
    p_limit = context.p_limit_mw
    t_hours = context.t_hours
    
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
        p_base_kw_realized, p_ev_kw_realized, p_tot_kw_realized = context.realization_traces(col_name)
        df_res = context.run(
            is_profiled=True,
            p_tot_kw_realized=p_tot_kw_realized,
            p_ev_kw_realized=p_ev_kw_realized,
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
    p_tot_mean = (context.p_base_kw_mean + context.p_ev_kw_mean) / 1000.0
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
        ax.set_ylim(y_min, y_max)
        ax.set_ylabel("Substation Power\nDemand [MW]", fontsize=12)
        apply_hour_axis(ax, start=0, end=28, step=4, label="", fontsize=14)
        style_timeseries_axis(ax)
        ax.legend(loc="upper left", fontsize=11, framealpha=0.9)
    
    ax_un.set_title(r"Multi-Scenario Recourse Validation: Dynamic Dispatch Performance",
                    fontsize=16, weight='bold')
    ax_un.tick_params(labelbottom=False)
    
    apply_hour_axis(ax_mg, start=0, end=28, step=4, fontsize=14)
    
    paths = save_figure_pair(fig, out_dir / "plot_16_stage_2_multiscenario.png")
    print(f"Saved PDF to {paths['pdf']}")
    print(f"Saved to {paths['png']}")
if __name__ == "__main__":
    main()
