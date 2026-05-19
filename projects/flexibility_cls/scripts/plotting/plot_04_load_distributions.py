"""
plot_04_load_distributions.py

Reads market dispatch timeseries and plots the unmanaged and managed load distributions
(Mean vs 95th percentile) to explicitly demonstrate how chance-constrained flexibility
contains the stochastic load within the dynamic limit.
"""

import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

PALETTE = {
    "unmanaged_mean": "#E87040",
    "unmanaged_p95": "#C0392B",
    "managed_mean": "#2C3E50",
    "managed_p95": "#2980B9",
    "limit": "#c0392b"
}

def main():
    print("="*60)
    print("  Generating Load Distribution Overlays...")
    print("="*60)
    
    data_dir = ROOT / "projects/flexibility_cls/outputs/data"
    fig_dir = ROOT / "projects/flexibility_cls/outputs/figures/02_stage1_stochastic_load"
    fig_dir.mkdir(parents=True, exist_ok=True)
    
    df_ts = pd.read_parquet(data_dir / "market_dispatch_timeseries.parquet")
    
    t_hours = df_ts["t_hours"].values
    
    # Unmanaged Stats
    p_unmanaged_mean = df_ts["p_baseline_mean_mw"].values + df_ts["p_ev_mean_mw"].values
    p_tot_std = df_ts["p_tot_std_mw"].values
    p_unmanaged_p95 = p_unmanaged_mean + 1.645 * p_tot_std
    
    # Managed Stats
    p_soft_cls = df_ts["p_soft_cls_mw"].values
    p_hard_cls = df_ts["p_hard_cls_mw"].values
    p_managed_mean = p_unmanaged_mean - p_soft_cls - p_hard_cls
    p_managed_p95 = p_managed_mean + 1.645 * p_tot_std
    
    p_thermal_limit = df_ts["p_limit_trace_mw"].values

    fig, axes = plt.subplots(1, 2, figsize=(16.0, 6.0), sharey=True)
    
    # --- PANEL 1: UNMANAGED LOAD ---
    ax1 = axes[0]
    ax1.plot(t_hours, p_thermal_limit, color=PALETTE["limit"], lw=2, ls="-.", label=r"Dynamic Limit ($\theta_H$)")
    ax1.plot(t_hours, p_unmanaged_mean, color=PALETTE["unmanaged_mean"], lw=2, label="Unmanaged Load (Mean)")
    ax1.plot(t_hours, p_unmanaged_p95, color=PALETTE["unmanaged_p95"], lw=2.5, ls="--", label="Unmanaged Load (95th Pctl)")
    ax1.fill_between(t_hours, p_unmanaged_mean, p_unmanaged_p95, color=PALETTE["unmanaged_mean"], alpha=0.15)
    
    ax1.set_title("A) Distribution of Unmanaged Load", fontsize=14, pad=15)
    ax1.set_ylabel("Demand (MW)", fontsize=12)
    ax1.set_xlabel("Hour of Day", fontsize=12)
    
    # --- PANEL 2: MANAGED LOAD ---
    ax2 = axes[1]
    ax2.plot(t_hours, p_thermal_limit, color=PALETTE["limit"], lw=2, ls="-.", label=r"Dynamic Limit ($\theta_H$)")
    ax2.plot(t_hours, p_managed_mean, color=PALETTE["managed_mean"], lw=2, label="Managed Load (Mean)")
    ax2.plot(t_hours, p_managed_p95, color=PALETTE["managed_p95"], lw=2.5, ls="--", label="Managed Load (95th Pctl)")
    ax2.fill_between(t_hours, p_managed_mean, p_managed_p95, color=PALETTE["managed_mean"], alpha=0.15)
    
    ax2.set_title("B) Distribution of Managed Load (With Flexibility)", fontsize=14, pad=15)
    ax2.set_xlabel("Hour of Day", fontsize=12)

    for ax in axes:
        ax.set_xlim(0, 26)
        ax.set_xticks(range(0, 27, 4))
        ax.set_xticklabels([f"{h%24:02d}:00" for h in range(0, 27, 4)], rotation=30, ha="right")
        ax.legend(loc="upper left", frameon=True, framealpha=1.0, facecolor="white").set_zorder(99)
        ax.grid(True, alpha=0.3)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
    
    fig.tight_layout()
    output_path = fig_dir / "load_distributions.png"
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    fig.savefig(fig_dir / "load_distributions.pdf", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> Saved load distributions plot to {output_path}\n")

if __name__ == "__main__":
    main()
