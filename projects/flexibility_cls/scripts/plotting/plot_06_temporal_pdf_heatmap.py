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

def main():
    print("="*60)
    print("  Generating Temporal Probability Density Heatmap...")
    print("="*60)
    
    data_dir = ROOT / "projects/flexibility_cls/outputs/data"
    fig_dir = ROOT / "projects/flexibility_cls/outputs/figures/03_stage2_thermal_screening"
    fig_dir.mkdir(parents=True, exist_ok=True)
    
    df_ts = pd.read_parquet(data_dir / "market_dispatch_timeseries.parquet")
    
    t_hours = df_ts["t_hours"].values
    
    # Unmanaged
    mu_unmanaged = df_ts["p_baseline_mean_mw"].values + df_ts["p_ev_mean_mw"].values
    sigma = df_ts["p_tot_std_mw"].values
    
    # Managed
    p_soft = df_ts["p_soft_cls_mw"].values
    p_hard = df_ts["p_hard_cls_mw"].values
    mu_managed = mu_unmanaged - p_soft - p_hard
    
    limit = df_ts["p_limit_trace_mw"].values
    
    # Create a grid for Y-axis (Power in MW)
    y_min = max(0, np.min(mu_managed - 3*sigma) - 2)
    y_max = np.max(mu_unmanaged + 3*sigma) + 2
    Y = np.linspace(y_min, y_max, 500)
    X = t_hours
    
    # Calculate Probability Densities over Time
    Z_unmanaged = np.zeros((len(Y), len(X)))
    Z_managed = np.zeros((len(Y), len(X)))
    
    for i in range(len(X)):
        if sigma[i] > 1e-6:
            Z_unmanaged[:, i] = stats.norm.pdf(Y, mu_unmanaged[i], sigma[i])
            Z_managed[:, i] = stats.norm.pdf(Y, mu_managed[i], sigma[i])
        else:
            Z_unmanaged[:, i] = 0
            Z_managed[:, i] = 0
            
    fig, axes = plt.subplots(1, 2, figsize=(16, 6), sharey=True, constrained_layout=True)
    
    # We will use a colormap that goes from white to dark blue
    cmap = "Blues"
    
    # Panel 1: Unmanaged
    ax1 = axes[0]
    c1 = ax1.pcolormesh(X, Y, Z_unmanaged, shading='auto', cmap=cmap, vmax=np.max(Z_unmanaged)*0.8)
    ax1.plot(X, limit, color="red", lw=2, ls="--", label="Dynamic Thermal Limit")
    ax1.plot(X, mu_unmanaged, color="black", lw=1.5, label="Expected Mean")
    
    # Add a visual marker for where probability exceeds the limit
    # We can overlay a red colormap for the region where Y > limit
    Z_risk = np.copy(Z_unmanaged)
    for i in range(len(X)):
        Z_risk[Y < limit[i], i] = np.nan  # hide safe regions
        Z_risk[Z_risk < 0.01] = np.nan # hide very low probabilities
        
    ax1.pcolormesh(X, Y, Z_risk, shading='auto', cmap="Reds", alpha=0.6)
    
    ax1.set_title("A) Unmanaged Load Probability Density over Time", fontsize=14, pad=15)
    ax1.set_ylabel("Power Demand (MW)", fontsize=12)
    ax1.set_xlabel("Hour of Day", fontsize=12)
    ax1.legend(loc="upper left")
    
    # Panel 2: Managed
    ax2 = axes[1]
    ax2.pcolormesh(X, Y, Z_managed, shading='auto', cmap=cmap, vmax=np.max(Z_unmanaged)*0.8)
    ax2.plot(X, limit, color="red", lw=2, ls="--", label="Dynamic Thermal Limit")
    ax2.plot(X, mu_managed, color="black", lw=1.5, label="Expected Mean")
    
    ax2.set_title("B) Managed Load Probability Density over Time", fontsize=14, pad=15)
    ax2.set_xlabel("Hour of Day", fontsize=12)
    ax2.legend(loc="upper left")
    
    for ax in axes:
        ax.set_xlim(0, 26)
        ax.set_xticks(range(0, 27, 4))
        ax.set_xticklabels([f"{h%24:02d}:00" for h in range(0, 27, 4)], rotation=30, ha="right")
        ax.grid(True, alpha=0.3, color="white", lw=0.5)
        
    # Colorbar
    cbar = fig.colorbar(c1, ax=axes, orientation='vertical', fraction=0.02, pad=0.02)
    cbar.set_label("Probability Density", fontsize=12)
    
    output_path = fig_dir / "temporal_probability_heatmap.png"
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    fig.savefig(fig_dir / "temporal_probability_heatmap.pdf", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> Saved Temporal PDF Heatmap to {output_path}\n")

if __name__ == "__main__":
    main()
