"""
plot_01_grid_exceedance.py

Reads the probabilistic generation data and writes:
- exceedance_probability.pdf
- flexibility_requirement.pdf
"""

import sys
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
from scipy.stats import norm

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "projects/flexibility_cls/outputs/data"
JSON_DIR = ROOT / "projects/flexibility_cls/outputs/json"
FIG_DIR = ROOT / "projects/flexibility_cls/outputs/figures/03_stage2_thermal_screening"
FIG_DIR.mkdir(parents=True, exist_ok=True)

def main():
    print("="*60)
    print("  Generating Grid Exceedance Visualizations...")
    print("="*60)
    
    with open(JSON_DIR / "flex_requirements.json", "r") as f:
        reqs = json.load(f)
        
    df_ts = pd.read_parquet(DATA_DIR / "congestion_temporal_bounds.parquet")
    peak_s2 = np.load(DATA_DIR / "s2_peak_vals.npy")
    peak_base = np.load(DATA_DIR / "base_peak_vals.npy")
    
    EV_PCT_LIST = reqs["ev_pct_list"]
    P_LIMIT_KW = reqs["p_limit_kw"]
    P_RATED_KW = reqs["p_rated_kw"]
    
    # ══════════════════════════════════════════════════════════════════════════════
    # Figure A — P(peak > P_limit) vs EV penetration
    # ══════════════════════════════════════════════════════════════════════════════
    fig, axes = plt.subplots(1, 2, figsize=(13.0, 5.0))
    
    ax = axes[0]
    ax.plot(EV_PCT_LIST, [p * 100 for p in reqs["prob_limit"]],
            "o-", color="#E74C3C", linewidth=2.5, markersize=8,
            label=f"$P > P_{{\\mathrm{{limit}}}}$ ({P_LIMIT_KW/1e3:.1f} MW)")
    ax.plot(EV_PCT_LIST, [p * 100 for p in reqs["prob_rated"]],
            "s--", color="#C0392B", linewidth=1.8, markersize=7, alpha=0.75,
            label=f"$P > P_{{\\mathrm{{rated}}}}$ ({P_RATED_KW/1e3:.1f} MW)")
    ax.fill_between(EV_PCT_LIST, [p * 100 for p in reqs["prob_limit"]],
                    [p * 100 for p in reqs["prob_rated"]],
                    alpha=0.12, color="#E74C3C", label="Amber zone")
    ax.axhline(100, color="#CCCCCC", linewidth=0.8, linestyle=":")
    ax.set_xlabel("EV Penetration (%)", fontsize=11)
    ax.set_ylabel("Probability of Thermal Limit Breach (%)", fontsize=11)
    ax.set_ylim(0, 105)
    ax.set_xticks(EV_PCT_LIST)
    ax.legend(fontsize=9, frameon=True, framealpha=1.0, facecolor="white", edgecolor="#CCCCCC").set_zorder(99)
    ax.grid(axis="y", color="#EAEAEA", linewidth=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    
    ax2 = axes[1]
    x      = np.array(EV_PCT_LIST)
    medians = np.array(reqs["medians_kw"]) / 1e3
    p5s     = np.array(reqs["p5s_kw"]) / 1e3
    p95s    = np.array(reqs["p95s_kw"]) / 1e3
    
    ax2.fill_between(x, p5s, p95s, color="#4A90D9", alpha=0.22, label="5–95% CI (MC)")
    ax2.plot(x, medians, "o-", color="#4A90D9", linewidth=2.5, markersize=8, label="Median peak (MW)")
    ax2.axhline(P_LIMIT_KW / 1e3, color="#E74C3C", linewidth=2.0,
                linestyle="--", label=f"$P_{{\\mathrm{{limit}}}}$ = {P_LIMIT_KW/1e3:.1f} MW")
    ax2.axhline(P_RATED_KW / 1e3, color="#C0392B", linewidth=1.3,
                linestyle="-.", alpha=0.7, label=f"$P_{{\\mathrm{{rated}}}}$ = {P_RATED_KW/1e3:.1f} MW")
    
    idx_30 = EV_PCT_LIST.index(30)
    d_req  = medians[idx_30] - P_LIMIT_KW / 1e3
    if d_req > 0:
        ax2.annotate(
            f"$D_{{\\mathrm{{req}}}}$ = {d_req:.2f} MW",
            xy=(30, P_LIMIT_KW / 1e3), xytext=(32, P_LIMIT_KW / 1e3 + 0.6),
            fontsize=9, color="#E74C3C",
            arrowprops=dict(arrowstyle="->", color="#E74C3C", lw=1.2),
        )
        ax2.annotate("", xy=(30, medians[idx_30]), xytext=(30, P_LIMIT_KW / 1e3),
                     arrowprops=dict(arrowstyle="<->", color="#E74C3C", lw=1.5))
                     
    ax2.set_xlabel("EV Penetration (%)", fontsize=11)
    ax2.set_ylabel("Peak Load (MW)", fontsize=11)
    ax2.set_xticks(EV_PCT_LIST)
    ax2.legend(fontsize=9, frameon=True, framealpha=1.0, facecolor="white", edgecolor="#CCCCCC").set_zorder(99)
    ax2.grid(axis="y", color="#EAEAEA", linewidth=0.8)
    ax2.spines["top"].set_visible(False)
    ax2.spines["right"].set_visible(False)
    
    fig.tight_layout(pad=2.5)
    fig.savefig(FIG_DIR / "exceedance_probability.pdf", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("  -> Saved exceedance_probability.pdf")
    
    # ══════════════════════════════════════════════════════════════════════════════
    # Figure B — MC sample trajectories + vertical marginal distribution at peak
    # ══════════════════════════════════════════════════════════════════════════════
    t_hours = df_ts["t_hours"].values
    p_limit_trace = df_ts["p_limit_trace"].values
    
    # --- Load raw MC realizations from parquet ---
    df_baseline = pd.read_parquet(DATA_DIR / "substation_baseline_mc.parquet")
    df_ev_cap   = pd.read_parquet(DATA_DIR / "substation_ev_capability_mc.parquet")
    
    # Reconstruct MC trajectories at substation level (already in MW in parquet)
    # baseline_mc columns are realizations, rows are timesteps
    # Scale EV: S2 = base + ev*(20/30), S4 = base + ev*(40/30)
    
    n_reals = df_baseline.shape[1]  # 30 realizations
    n_steps = min(len(t_hours), df_baseline.shape[0])
    
    # Build MC trajectory matrices: (n_reals, n_steps) in MW
    base_vals = df_baseline.values[:n_steps, :]
    ev_vals   = df_ev_cap.values[:n_steps, :]
    base_mc = base_vals.T                                        # (30, n_steps) MW
    s2_mc   = (base_vals + ev_vals * (20.0/30.0)).T              # (30, n_steps) MW
    s4_mc   = (base_vals + ev_vals * (40.0/30.0)).T              # (30, n_steps) MW
    
    # Compute peak values at peak hour for S4 KDE
    peak_idx_ts = int(np.argmax(np.median(s2_mc, axis=0)))
    peak_s4 = s4_mc[:, peak_idx_ts]
    
    fig = plt.figure(figsize=(14.0, 6.0))
    gs  = fig.add_gridspec(1, 2, width_ratios=[3, 1], hspace=0, wspace=0.04)
    ax_ts  = fig.add_subplot(gs[0])
    ax_kde = fig.add_subplot(gs[1], sharey=ax_ts)
    
    # --- Plot individual MC sample trajectories ---
    # Base trajectories (blue, thin, transparent)
    for i in range(n_reals):
        label = "Base (0% EV)" if i == 0 else None
        ax_ts.plot(t_hours[:n_steps], base_mc[i], color="#4A90D9", alpha=0.15,
                   linewidth=0.5, zorder=2, label=label)
    
    # S2 trajectories (red, thin, transparent)
    for i in range(n_reals):
        label = "S2 (+20% EV)" if i == 0 else None
        ax_ts.plot(t_hours[:n_steps], s2_mc[i], color="#E74C3C", alpha=0.18,
                   linewidth=0.5, zorder=3, label=label)
    
    # S4 trajectories (orange, thin, transparent)
    for i in range(n_reals):
        label = "S4 (+40% EV)" if i == 0 else None
        ax_ts.plot(t_hours[:n_steps], s4_mc[i], color="#E67E22", alpha=0.22,
                   linewidth=0.5, zorder=4, label=label)
    
    # Median lines (thicker, solid)
    base_median = np.median(base_mc, axis=0)
    s2_median   = np.median(s2_mc, axis=0)
    s4_median   = np.median(s4_mc, axis=0)
    ax_ts.plot(t_hours[:n_steps], base_median, color="#1A5276", linewidth=2.0,
               linestyle="-", zorder=6, label="Base median")
    ax_ts.plot(t_hours[:n_steps], s2_median, color="#C0392B", linewidth=2.0,
               linestyle="-", zorder=7, label="S2 median")
    ax_ts.plot(t_hours[:n_steps], s4_median, color="#A04000", linewidth=2.5,
               linestyle="-", zorder=8, label="S4 median")
    
    # Dynamic thermal limit
    from projects.flexibility_cls.scripts.config import THETA_MAX as _tm
    ax_ts.plot(t_hours[:n_steps], p_limit_trace[:n_steps], color="#34495E", linewidth=2.0, linestyle="--",
               label=fr"$P_{{\mathrm{{limit}}}}(t)$ (dynamic thermal, $\theta_{{\max}}={_tm:.0f}^\circ$C)", zorder=9)
               
    # Peak hour marker
    peak_hour = reqs["peak_hour"]
    ax_ts.axvline(peak_hour, color="#8E44AD", linewidth=1.6, linestyle=":", zorder=5, label=f"Peak: {peak_hour:.1f} h")
    
    # D_tar annotation
    D_tar = reqs["D_tar_mw"]
    limit_at_peak = reqs["limit_at_peak_mw"]
    peak_D_tar_abs = limit_at_peak + D_tar
    
    if D_tar > 0:
        ax_ts.annotate("", xy=(peak_hour, limit_at_peak),
                       xytext=(peak_hour, peak_D_tar_abs),
                       arrowprops=dict(arrowstyle="<->", color="#27AE60", lw=2.0))
        ax_ts.text(peak_hour + 1.2, limit_at_peak + (D_tar / 2),
                   f"$D_{{\\mathrm{{tar}}}}$ ≈ {D_tar:.2f} MW",
                   fontsize=10, fontweight="bold", color="#1B4F72", va="center", ha="left",
                   bbox=dict(facecolor="white", edgecolor="none", alpha=1.0, pad=2.5), zorder=10)
                   
    ax_ts.set_xlabel("Hour of day", fontsize=11)
    ax_ts.set_ylabel("Substation load (MW)", fontsize=11)
    ax_ts.set_xlim(0, 24)
    y_min_val = np.min(base_mc)
    y_max_val = max(np.max(s4_mc), np.max(p_limit_trace[:n_steps]))
    ax_ts.set_ylim(bottom=y_min_val - 0.5, top=y_max_val + 1.5)
    
    tick_start, tick_end = 0, 25
    ax_ts.set_xticks(range(tick_start, tick_end, 4))
    ax_ts.set_xticklabels([f"{h:02d}:00" for h in range(tick_start, tick_end, 4)], rotation=30, ha="right", fontsize=8)
    ax_ts.legend(loc="upper left", fontsize=7.5, ncol=2, frameon=True, facecolor="white").set_zorder(99)
    ax_ts.grid(axis="y", color="#EAEAEA", linewidth=0.8)
    ax_ts.spines["top"].set_visible(False)
    ax_ts.spines["right"].set_visible(False)
    
    # --- KDE marginal at peak hour (Base, S2, S4) ---
    pv_range = np.linspace(peak_base.min() - 0.3, peak_s4.max() + 0.3, 500)
    base_kde_vals = norm.pdf(pv_range, reqs["mu_base"], reqs["std_base"])
    s2_kde_vals   = norm.pdf(pv_range, reqs["mu_peak"], reqs["std_peak"])
    s4_kde_vals   = norm.pdf(pv_range, np.mean(peak_s4), np.std(peak_s4))
    
    ax_kde.fill_betweenx(pv_range, 0, base_kde_vals, color="#4A90D9", alpha=0.30, label="Base PDF", zorder=2)
    ax_kde.plot(base_kde_vals, pv_range, color="#1A5276", linewidth=1.5, zorder=3)
    
    ax_kde.fill_betweenx(pv_range, 0, s2_kde_vals, color="#E74C3C", alpha=0.30, label="S2 PDF", zorder=4)
    ax_kde.plot(s2_kde_vals, pv_range, color="#C0392B", linewidth=1.5, zorder=5)
    
    ax_kde.fill_betweenx(pv_range, 0, s4_kde_vals, color="#E67E22", alpha=0.30, label="S4 PDF", zorder=6)
    ax_kde.plot(s4_kde_vals, pv_range, color="#A04000", linewidth=2.0, zorder=7)
    
    # Overload zone for S4
    mask_over = pv_range > limit_at_peak
    frac_s4_over = float(np.mean(peak_s4 > limit_at_peak) * 100)
    ax_kde.fill_betweenx(pv_range[mask_over], s4_kde_vals[mask_over],
                         color="#E67E22", alpha=0.40, label=f"S4 overload ({frac_s4_over:.0f}%)")
    
    ax_kde.axhline(limit_at_peak, color="#34495E", linewidth=1.8, linestyle="--")
    ax_kde.axhline(np.median(peak_s2), color="#C0392B", linewidth=1.2, linestyle="-.",
                   label=f"S2 med. {np.median(peak_s2):.2f} MW")
    ax_kde.axhline(np.median(peak_s4), color="#A04000", linewidth=1.2, linestyle="-.",
                   label=f"S4 med. {np.median(peak_s4):.2f} MW")
    
    ax_kde.set_xlabel("Density", fontsize=9)
    ax_kde.tick_params(axis="y", labelleft=False)
    ax_kde.tick_params(axis="x", labelsize=7)
    ax_kde.legend(loc="lower right", fontsize=7.0, frameon=True, facecolor="white").set_zorder(99)
    ax_kde.spines["top"].set_visible(False)
    ax_kde.spines["right"].set_visible(False)
    ax_kde.grid(axis="y", color="#EAEAEA", linewidth=0.8)
    
    fig.tight_layout()
    fig.savefig(FIG_DIR / "flexibility_requirement.pdf", dpi=200, bbox_inches="tight")
    fig.savefig(FIG_DIR / "flexibility_requirement.png", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print("  -> Saved flexibility_requirement.pdf\n")

if __name__ == "__main__":
    main()
