import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import scipy.stats as stats
from pathlib import Path

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from projects.flexibility_cls.scripts.config import S_RATED_KVA, THETA_MAX

def main():
    print("="*60)
    print("  Generating Power Probability Density Heatmap...")
    print("="*60)
    
    data_dir = ROOT / "projects/flexibility_cls/outputs/data"
    fig_dir = ROOT / "projects/flexibility_cls/outputs/figures/04_stage3_market_clearing"
    fig_dir.mkdir(parents=True, exist_ok=True)
    
    df_ts = pd.read_parquet(data_dir / "market_dispatch_timeseries.parquet")
    t_hours = df_ts["t_hours"].values
    n_steps = len(t_hours)
    
    # Unmanaged
    mu_unmanaged = df_ts["p_baseline_mean_mw"].values + df_ts["p_ev_mean_mw"].values
    sigma = df_ts["p_tot_std_mw"].values
    
    # Managed
    p_soft_mw = df_ts["p_soft_cls_mw"].values
    p_hard_mw = df_ts["p_hard_cls_mw"].values
    p_flex_mw = p_soft_mw + p_hard_mw
    
    # Load actual MC traces
    from projects.flexibility_cls.scripts.data_api import get_baseline_building_load_all
    try:
        bldg_realizations = get_baseline_building_load_all()[:, :n_steps] / 1000.0 # MW
    except Exception as e:
        print(f"Error loading realizations: {e}")
        return
            
    N_TRACES = bldg_realizations.shape[0]
    
    p_ev_mw = df_ts["p_ev_mean_mw"].values
    
    # Calculate DSO activation threshold in MW
    z_score = stats.norm.ppf(0.95)
    p_worst_mw = (mu_unmanaged + z_score * sigma)
    p_threshold_mw = p_worst_mw - p_flex_mw
    
    p_unmanaged_traces = np.zeros((N_TRACES, n_steps))
    p_managed_traces = np.zeros((N_TRACES, n_steps))
    
    print(f"  Calculating {N_TRACES} power traces...")
    for i in range(N_TRACES):
        p_unmanaged_trace = bldg_realizations[i] + p_ev_mw
        curtailment = np.clip(p_unmanaged_trace - p_threshold_mw, 0, p_flex_mw)
        p_managed_trace = p_unmanaged_trace - curtailment
        
        p_unmanaged_traces[i, :] = p_unmanaged_trace
        p_managed_traces[i, :] = p_managed_trace
        
    # Create 2D grid for Power
    y_min = max(0, np.min(p_managed_traces) - 2)
    y_max = np.max(p_unmanaged_traces) + 2
    Y = np.linspace(y_min, y_max, 200)
    X = t_hours
    
    Z_unmanaged = np.zeros((len(Y), len(X)))
    Z_managed = np.zeros((len(Y), len(X)))
    
    # Calculate density for each timestep using KDE
    for t in range(n_steps):
        traces_un = p_unmanaged_traces[:, t]
        traces_mn = p_managed_traces[:, t]
        if np.std(traces_un) < 1e-4: traces_un += np.random.normal(0, 1e-3, N_TRACES)
        if np.std(traces_mn) < 1e-4: traces_mn += np.random.normal(0, 1e-3, N_TRACES)
        
        kde_unmanaged = stats.gaussian_kde(traces_un)
        kde_managed = stats.gaussian_kde(traces_mn)
        
        Z_unmanaged[:, t] = kde_unmanaged(Y)
        Z_managed[:, t] = kde_managed(Y)
        
    fig, axes = plt.subplots(1, 2, figsize=(16, 6), sharey=True, constrained_layout=True)
    cmap = "Blues"
    
    # Panel 1: Unmanaged
    ax1 = axes[0]
    c1 = ax1.pcolormesh(X, Y, Z_unmanaged, shading='auto', cmap=cmap, vmax=np.max(Z_unmanaged)*0.8)
    ax1.plot(X, p_threshold_mw, color="red", lw=2, ls="--", label="DSO Activation Threshold")
    ax1.plot(X, np.mean(p_unmanaged_traces, axis=0), color="black", lw=1.5, label="Expected Mean Power")
    
    # Overlay risk
    Z_risk = np.copy(Z_unmanaged)
    for i in range(len(X)):
        Z_risk[Y < p_threshold_mw[i], i] = np.nan
        Z_risk[Z_risk < 0.01] = np.nan
        
    ax1.pcolormesh(X, Y, Z_risk, shading='auto', cmap="Reds", alpha=0.6)
    
    ax1.set_title("A) Unmanaged Power Probability Density", fontsize=14, pad=15)
    ax1.set_ylabel("Total Power (MW)", fontsize=12)
    ax1.set_xlabel("Hour of Day", fontsize=12)
    ax1.legend(loc="upper left")
    
    # Panel 2: Managed
    ax2 = axes[1]
    c2 = ax2.pcolormesh(X, Y, Z_managed, shading='auto', cmap=cmap, vmax=np.max(Z_unmanaged)*0.8)
    ax2.plot(X, p_threshold_mw, color="red", lw=2, ls="--", label="DSO Activation Threshold")
    ax2.plot(X, np.mean(p_managed_traces, axis=0), color="black", lw=1.5, label="Expected Mean Power")
    
    ax2.set_title("B) Managed Power Probability Density", fontsize=14, pad=15)
    ax2.set_xlabel("Hour of Day", fontsize=12)
    ax2.legend(loc="upper left")
    
    for ax in axes:
        ax.set_xlim(0, 26)
        ax.set_xticks(range(0, 27, 4))
        ax.set_xticklabels([f"{h%24:02d}:00" for h in range(0, 27, 4)], rotation=30, ha="right")
        ax.grid(True, alpha=0.3, color="white", lw=0.5)
        ax.set_ylim(min(10, y_min), max(25, y_max))
        
    # Colorbar
    cbar = fig.colorbar(c1, ax=axes, orientation='vertical', fraction=0.02, pad=0.02)
    cbar.set_label("Probability Density", fontsize=12)
    
    output_path = fig_dir / "power_probability_heatmap.png"
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    fig.savefig(fig_dir / "power_probability_heatmap.pdf", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> Saved Power PDF Heatmap to {output_path}\n")

if __name__ == "__main__":
    main()
