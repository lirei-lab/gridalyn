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

def main():
    data_dir = ROOT / "projects/flexibility_cls/outputs/data"
    out_dir = ROOT / "projects/flexibility_cls/outputs/figures/05_stage4_realtime_dispatch"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    df_base = pd.read_parquet(data_dir / "substation_baseline_mc.parquet")
    df_ev = pd.read_parquet(data_dir / "substation_ev_capability_mc.parquet")
    
    p_base_kw_mean = df_base.mean(axis=1).values * 1000.0
    p_base_kw_std = df_base.std(axis=1).values * 1000.0
    p_ev_kw_mean = df_ev.mean(axis=1).values * 1000.0 * (30.0 / 30.0) 
    p_ev_kw_std = df_ev.std(axis=1).values * 1000.0 * (30.0 / 30.0)
    
    tmy = download_tmy()
    cold_day = select_cold_day(tmy, duration_hours=28)
    t_out_trace = cold_day["temp_air"].resample(f"{RES_MINUTES}min").interpolate().values
    
    from gridalyn.assets.datagen.grid.transformer_thermal import TransformerThermalModel
    thermal_model = TransformerThermalModel(theta_max=THETA_MAX, s_rated_kva=S_RATED_KVA)
    network = MVNetwork(thermal_model=thermal_model, p_rated_kw=P_LIMIT_KW)
    dt_h = RES_MINUTES / 60.0
    dispatcher = DSODispatcher(network=network, dt_man_h=dt_h, epsilon=0.05, stochastic_failure_rate=0.05)
    market_engine = MarketSimulationEngine(network=network, dispatcher=dispatcher)
    
    # Run the simulation
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
        is_profiled=True,
        market_resolution_h=0.5
    )
    
    t_hours = np.arange(len(p_base_kw_mean)) * (RES_MINUTES / 60)
    
    # Extract deficit columns
    deficit_cols = [c for c in df_res.columns if c.startswith("deficit_")]
    
    fig, ax = plt.subplots(figsize=(14, 7))
    
    # Use a colormap to differentiate the aggregators
    import matplotlib.cm as cm
    cmap = plt.get_cmap('viridis')
        
    colors = cmap(np.linspace(0, 1, len(deficit_cols)))
    
    for i, col in enumerate(deficit_cols):
        ax.plot(t_hours, df_res[col].values, color=colors[i], lw=2, alpha=0.8, label=f"Aggregator {col.split('_')[1]}")
    
    ax.set_ylabel("Accumulated Thermal Deficit [kWh]", fontsize=14)
    
    ax.set_title("Aggregator Thermal Deficit Trajectories (Profiled Dimensioning)", fontsize=18, weight='bold')
    
    ax.set_xlim(0, 28)
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
    
    # Only show a subset of legends if there are too many
    handles, labels = ax.get_legend_handles_labels()
    if len(handles) > 8:
        subset_indices = np.linspace(0, len(handles)-1, 8, dtype=int)
        ax.legend([handles[i] for i in subset_indices], [labels[i] for i in subset_indices], loc="upper left", fontsize=12, framealpha=0.9, title="Sample Aggregators")
    else:
        ax.legend(loc="upper left", fontsize=12, framealpha=0.9)
        
    plt.tight_layout()
    
    out_path = out_dir / "plot_18_aggregator_deficits.png"
    out_pdf_path = out_path.with_suffix(".pdf")
    fig.savefig(out_pdf_path, bbox_inches="tight")
    print(f"Saved PDF to {out_pdf_path}")

    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    print(f"Saved to {out_path}")

if __name__ == "__main__":
    main()
