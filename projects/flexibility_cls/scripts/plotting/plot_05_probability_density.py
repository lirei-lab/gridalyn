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

PALETTE = {
    "unmanaged": "#E87040",
    "managed": "#2980B9",
    "limit": "#C0392B",
    "risk": "#E74C3C"
}

def main():
    print("="*60)
    print("  Generating Chance-Constrained PDF Illustration...")
    print("="*60)
    
    data_dir = ROOT / "projects/flexibility_cls/outputs/data"
    fig_dir = ROOT / "projects/flexibility_cls/outputs/figures/03_stage2_thermal_screening"
    fig_dir.mkdir(parents=True, exist_ok=True)
    
    df_ts = pd.read_parquet(data_dir / "market_dispatch_timeseries.parquet")
    
    # Calculate Unmanaged and Managed series
    df_ts["p_unmanaged_mean"] = df_ts["p_baseline_mean_mw"] + df_ts["p_ev_mean_mw"]
    df_ts["p_managed_mean"] = df_ts["p_unmanaged_mean"] - df_ts["p_soft_cls_mw"] - df_ts["p_hard_cls_mw"]
    
    # Find the peak unmanaged hour to illustrate the worst-case moment
    peak_idx = df_ts["p_unmanaged_mean"].argmax()
    
    mu_unmanaged = df_ts["p_unmanaged_mean"].iloc[peak_idx]
    mu_managed = df_ts["p_managed_mean"].iloc[peak_idx]
    sigma = df_ts["p_tot_std_mw"].iloc[peak_idx]
    limit = df_ts["p_limit_trace_mw"].iloc[peak_idx]
    
    # Setup the X axis for the PDF
    x = np.linspace(mu_managed - 4*sigma, mu_unmanaged + 4*sigma, 1000)
    
    # Calculate PDFs
    pdf_unmanaged = stats.norm.pdf(x, mu_unmanaged, sigma)
    pdf_managed = stats.norm.pdf(x, mu_managed, sigma)
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Plot Unmanaged
    ax.plot(x, pdf_unmanaged, color=PALETTE["unmanaged"], lw=2, label="Unmanaged Load Forecast")
    ax.fill_between(x, 0, pdf_unmanaged, color=PALETTE["unmanaged"], alpha=0.1)
    
    # Shade Overload Risk for Unmanaged
    x_risk = x[x >= limit]
    pdf_risk = stats.norm.pdf(x_risk, mu_unmanaged, sigma)
    ax.fill_between(x_risk, 0, pdf_risk, color=PALETTE["risk"], alpha=0.5, hatch="///", label="Unmanaged Overload Risk")
    
    # Plot Managed
    ax.plot(x, pdf_managed, color=PALETTE["managed"], lw=2, label="Managed Load (After CLS)")
    ax.fill_between(x, 0, pdf_managed, color=PALETTE["managed"], alpha=0.2)
    
    # Shade Managed Risk (alpha = 0.05)
    pdf_risk_managed = stats.norm.pdf(x_risk, mu_managed, sigma)
    ax.fill_between(x_risk, 0, pdf_risk_managed, color=PALETTE["managed"], alpha=0.8, label=r"Controlled Risk ($\alpha = 5\%$)")
    
    # Plot Limit Line
    ax.axvline(limit, color=PALETTE["limit"], lw=2.5, ls="--", label=r"Dynamic Thermal Limit ($P_{\mathrm{limit}}$)")
    
    # Annotations
    d_tar = mu_unmanaged - mu_managed
    ax.annotate(f"", xy=(mu_managed, 0.4), xytext=(mu_unmanaged, 0.4),
                arrowprops=dict(arrowstyle="->", color="black", lw=1.5))
    ax.text((mu_unmanaged + mu_managed)/2, 0.42, f"Purchased Flexibility ($D_{{\\mathrm{{tar}}}}$)\n{d_tar:.2f} MW", 
            ha='center', va='bottom', fontsize=11, fontweight='bold', bbox=dict(facecolor='white', alpha=0.8, edgecolor='none'))
            
    # Add Z_95 visualization
    ax.annotate(f"", xy=(limit, 0.1), xytext=(mu_managed, 0.1),
                arrowprops=dict(arrowstyle="<->", color=PALETTE["managed"], lw=1.5))
    ax.text((mu_managed + limit)/2, 0.12, r"$Z_{95} \sigma$", 
            ha='center', va='bottom', fontsize=11, color=PALETTE["managed"], fontweight='bold', bbox=dict(facecolor='white', alpha=0.8, edgecolor='none'))

    ax.set_title("Stochastic Chance-Constrained Flexibility Procurement (Peak Hour)", fontsize=14, pad=15)
    ax.set_xlabel("Power Demand (MW)", fontsize=12)
    ax.set_ylabel("Probability Density", fontsize=12)
    ax.set_xlim(x[0], x[-1])
    ax.set_ylim(bottom=0)
    
    ax.legend(loc="upper left", frameon=True, framealpha=0.9, facecolor="white", fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    
    fig.tight_layout()
    output_path = fig_dir / "chance_constrained_pdf.png"
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    fig.savefig(fig_dir / "chance_constrained_pdf.pdf", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> Saved PDF illustration plot to {output_path}\n")

if __name__ == "__main__":
    main()
