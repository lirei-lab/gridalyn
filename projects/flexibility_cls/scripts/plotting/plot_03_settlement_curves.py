"""
plot_03_settlement_curves.py

Generates diagnostic Soft-CLS capacity-credit sensitivity curves.
Reads the cleared market price from ev_summary_results.json
"""

import sys
import json
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
from scipy.stats import truncnorm

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from projects.flexibility_cls.scripts.config import EV_CHARGER_KW, NON_DELIVERY_PENALTY

JSON_DIR = ROOT / "projects/flexibility_cls/outputs/json"
FIG_DIR = ROOT / "projects/flexibility_cls/outputs/figures/06_stage5_settlement"
FIG_DIR.mkdir(parents=True, exist_ok=True)

# Base configuration constants
EV_COINCIDENCE = 0.72

# Diagnostic settlement sensitivity parameters
LAMBDA_PEN_PER_KWH = NON_DELIVERY_PENALTY
DELTA_T_MAN_H      = 4.3
C_SOFT_VALUES      = [1.0, 2.5, 5.0, 8.0, 12.0]
N_HH_PER_BLOCK     = 50
P_CHARGER_KW       = EV_CHARGER_KW

def main():
    print("="*60)
    print("  Generating Settlement Capacity-Credit Sensitivity...")
    print("="*60)
    
    with open(JSON_DIR / "ev_summary_results.json", "r") as f:
        res = json.load(f)
        
    c_mark = res.get("s2_clearing_price", 2.50)
    
    P_CAP_MAX_KW = N_HH_PER_BLOCK * 0.30 * P_CHARGER_KW * EV_COINCIDENCE
    DELTA_T = DELTA_T_MAN_H
    
    colors_price = ["#D6EAF8", "#85C1E9", "#3498DB", "#1A5276", "#0B2545"]
    fig, axes = plt.subplots(1, 2, figsize=(13.0, 5.5))
    
    ax = axes[0]
    for i, c_soft in enumerate(C_SOFT_VALUES):
        ratio = min(c_soft / (LAMBDA_PEN_PER_KWH * DELTA_T), 0.99)
        mu_bid    = ratio * P_CAP_MAX_KW
        sigma_bid = 0.15 * P_CAP_MAX_KW
        x_range   = np.linspace(0, P_CAP_MAX_KW * 1.05, 500)
        a_trunc = (0 - mu_bid) / sigma_bid
        b_trunc = (P_CAP_MAX_KW - mu_bid) / sigma_bid
        rv = truncnorm(a_trunc, b_trunc, loc=mu_bid, scale=sigma_bid)
        
        ax.fill_between(x_range, rv.pdf(x_range), alpha=0.45,
                        color=colors_price[i], label=f"$c^{{\\mathrm{{soft}}}}$ = \\${c_soft:.1f}/kW/h")
        ax.plot(x_range, rv.pdf(x_range), color=colors_price[i], linewidth=1.6)
        ax.axvline(mu_bid, color=colors_price[i], linewidth=0.8, linestyle=":", alpha=0.7)

    ax.set_xlim(0, P_CAP_MAX_KW * 1.1)
    ax.set_xlabel("Requested Soft-CLS credit $Q^{\\mathrm{CLS}}_i$ (kW / block)", fontsize=11)
    ax.set_ylabel("Probability density", fontsize=11)
    ax.legend(fontsize=9, loc="upper right", frameon=True, facecolor="white").set_zorder(99)
    ax.grid(axis="y", color="#EAEAEA", linewidth=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    ax2 = axes[1]
    c_sweep   = np.linspace(0.5, 14, 200)
    mu_sweep, p5_sweep, p95_sweep = [], [], []

    for c_soft in c_sweep:
        ratio     = min(c_soft / (LAMBDA_PEN_PER_KWH * DELTA_T), 0.99)
        mu_bid    = ratio * P_CAP_MAX_KW
        sigma_bid = 0.15 * P_CAP_MAX_KW
        a_trunc   = (0 - mu_bid) / sigma_bid
        b_trunc   = (P_CAP_MAX_KW - mu_bid) / sigma_bid
        rv = truncnorm(a_trunc, b_trunc, loc=mu_bid, scale=sigma_bid)
        mu_sweep.append(rv.mean())
        p5_sweep.append(rv.ppf(0.05))
        p95_sweep.append(rv.ppf(0.95))

    mu_sweep  = np.array(mu_sweep)
    p5_sweep  = np.array(p5_sweep)
    p95_sweep = np.array(p95_sweep)

    ax2.fill_between(c_sweep, p5_sweep, p95_sweep, color="#3498DB", alpha=0.18,
                     label="5–95% CI of requested $Q^{\\mathrm{CLS}}_i$")
    ax2.plot(c_sweep, mu_sweep, color="#1A5276", linewidth=2.4,
             label="Expected requested credit $\\mathbb{E}[Q^{\\mathrm{CLS}}_i | \\lambda]$")

    ratio  = min(c_mark / (LAMBDA_PEN_PER_KWH * DELTA_T), 0.99)
    mu_mark = ratio * P_CAP_MAX_KW
    ax2.axvline(c_mark, color="#E87040", linewidth=1.8, linestyle="--", alpha=0.85,
                label=f"Auction clearing price (${c_mark:.2f}/kW/h)")
    ax2.plot(c_mark, mu_mark, "o", color="#E87040", markersize=9, zorder=5)
    ax2.annotate(f"{mu_mark:.1f} kW",
                 xy=(c_mark, mu_mark), xytext=(c_mark + 0.8, mu_mark - 1.0),
                 fontsize=9, color="#E87040",
                 arrowprops=dict(arrowstyle="->", color="#E87040", lw=1.0))

    c_sat = LAMBDA_PEN_PER_KWH * DELTA_T
    ax2.axvline(c_sat, color="#8E44AD", linewidth=1.2, linestyle=":",
                label=f"Saturation ($c^{{\\mathrm{{soft}}}} = \\lambda_{{\\mathrm{{pen}}}}\\Delta T$)\\n${c_sat:.1f}/kW/h")

    ax2.set_xlim(0, 15)
    ax2.set_xlabel("Market price $\\lambda$ (\\$/kW/h)", fontsize=11)
    ax2.set_ylabel("Requested Soft-CLS credit (kW/block)", fontsize=11)
    ax2.legend(fontsize=9, loc="upper left", frameon=True, facecolor="white").set_zorder(99)
    ax2.grid(axis="y", color="#EAEAEA", linewidth=0.8)
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)

    fig.tight_layout(pad=2.5)
    fig.savefig(FIG_DIR / "cls_conditional_distributions.pdf", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("  -> Saved cls_conditional_distributions.pdf\n")

if __name__ == "__main__":
    main()
