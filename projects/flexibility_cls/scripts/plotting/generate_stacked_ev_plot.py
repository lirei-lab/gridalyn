"""
generate_stacked_ev_plot.py
============================
Workflow-driven figure: stacked building + EV load profile across penetration scenarios.

Data source:
  - substation_baseline_mc.parquet (building MC, written by pipeline 00)
  - substation_ev_capability_mc.parquet (EV MC at 30% penetration, written by pipeline 00)

S0..S4 (0/10/20/30/40%) are obtained by linearly scaling the 30% MC EV trace by pct/30.
Linear scaling assumes uniform spatial penetration, which is consistent with the
arrival-sampling model used in pipeline 00.

    uv run python projects/flexibility_cls/scripts/plotting/generate_stacked_ev_plot.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.assets.datagen.data.weather import download_tmy, select_peak_load_day
from gridalyn.assets.modeling.transformers import TransformerThermalModel
from projects.flexibility_cls.scripts.data_api import (
    get_baseline_building_load_all,
    get_ev_capability_load_all,
)

from projects.flexibility_cls.scripts.config import (
    N_BUILDINGS, S_RATED_KVA, P_RATED_KW, THETA_MAX,
    RES_MINUTES, EV_PERCENTAGES,
)

# Pipeline 00 generates the EV parquet at this fixed penetration.
EV_PARQUET_PCT = 30.0
EV_SCENARIOS = EV_PERCENTAGES

OUTPUTS_DIR = ROOT / "projects" / "flexibility_cls" / "outputs" / "figures" / "02_stage1_stochastic_load"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

PALETTE = {"buildings": "#4A90D9", "outdoor_temp": "#7B61FF"}
EV_COLORS = ["#FDEBD0", "#F9B27A", "#F28040", "#D95319", "#8B3014"][: len(EV_SCENARIOS)]

# Golden ratio (~1.618:1) — used for figure aspect.
GOLDEN = (1.0 + 5.0 ** 0.5) / 2.0
FIG_HEIGHT_IN = 6.8
FIG_WIDTH_IN = FIG_HEIGHT_IN * GOLDEN  # ~11.0 inches


def main():
    print("=" * 65)
    print("  Building + EV Stacked Load Profile (workflow-driven)")
    print(f"  Grid: {N_BUILDINGS} buildings | {S_RATED_KVA/1000:.0f} MVA substation")
    print("=" * 65)

    print("\n[1/3] Loading TMY peak-demand day for thermal limit & ambient curve...")
    tmy = download_tmy()
    # Match the 28-hour peak-demand window used by pipeline 00 so the figure
    # spans exactly the same simulation horizon (midnight day 1 -> 04:00 day 2).
    peak_day = select_peak_load_day(tmy, duration_hours=28)
    t_out = peak_day["temp_air"].resample(f"{RES_MINUTES}min").mean()
    n_steps = len(t_out)
    ambient = t_out.values.astype(float)
    ts_index = t_out.index  # carries real clock-time per timestep

    model_limit = TransformerThermalModel(s_rated_kva=S_RATED_KVA, theta_max=THETA_MAX)
    p_thermal_limit = np.array(
        [model_limit.max_load_for_temp(ambient[i]) for i in range(n_steps)]
    )

    print("[2/3] Reading building & EV MC profiles from parquet...")
    bldg_runs_kw = get_baseline_building_load_all()[:, :n_steps]
    ev_runs_kw = get_ev_capability_load_all()[:, :n_steps]
    n_realizations = bldg_runs_kw.shape[0]
    print(f"  {n_realizations} realizations | EV parquet @ {EV_PARQUET_PCT:.0f}% penetration")

    p_bldg_median = np.median(bldg_runs_kw, axis=0)
    p_bldg_p5 = np.percentile(bldg_runs_kw, 5, axis=0)
    p_bldg_p95 = np.percentile(bldg_runs_kw, 95, axis=0)
    p_ev_median_30pct = np.median(ev_runs_kw, axis=0)
    print(f"  Building median peak: {p_bldg_median.max()/1e3:.1f} MW")

    print(f"[3/3] Scaling EV trace to {len(EV_SCENARIOS)} scenarios...")
    ev_profiles = {
        pct: p_ev_median_30pct * (pct / EV_PARQUET_PCT) for pct in EV_SCENARIOS
    }
    for pct, p_ev in ev_profiles.items():
        peak_mw = (p_bldg_median + p_ev).max() / 1e3
        print(f"  S({pct:2d}%): total peak = {peak_mw:.2f} MW")

    print("\nGenerating figure...")
    # Use the real clock time of every timestep — the simulation horizon may
    # span across midnight, so labels are derived from the actual timestamp.
    t_hours = np.arange(n_steps) * RES_MINUTES / 60.0
    h_max = t_hours[-1]
    x_ticks = np.arange(0, h_max + 0.001, 4)
    sim_start = ts_index[0]
    x_labels = [
        (sim_start + pd.Timedelta(hours=float(h))).strftime("%H:%M")
        for h in x_ticks
    ]

    fig, ax1 = plt.subplots(figsize=(FIG_WIDTH_IN, FIG_HEIGHT_IN))

    ax1.fill_between(
        t_hours, p_bldg_p5 / 1e3, p_bldg_p95 / 1e3,
        color=PALETTE["buildings"], alpha=0.18, zorder=1,
        label="Building 5–95 % (90% CI)",
    )

    prev_total_mw = p_bldg_median / 1e3
    for pct, col in zip(EV_SCENARIOS, EV_COLORS):
        total_mw = (p_bldg_median + ev_profiles[pct]) / 1e3
        ax1.fill_between(
            t_hours, prev_total_mw, total_mw,
            color=col, alpha=0.80, zorder=2,
            label=f"+ EV ({pct}% penetration)",
        )
        prev_total_mw = total_mw

    top_mw = (p_bldg_median + ev_profiles[EV_SCENARIOS[-1]]) / 1e3
    ax1.plot(
        t_hours, top_mw, color=EV_COLORS[-1], linewidth=2.0,
        zorder=10, alpha=0.9,
        label=f"Total max scenario ({EV_SCENARIOS[-1]}%)",
    )

    ax1.plot(
        t_hours, p_bldg_median / 1e3,
        color=PALETTE["buildings"], linewidth=2.2, zorder=11,
        label="Building median",
    )

    ax1.plot(
        t_hours, p_thermal_limit / 1e3, color="#C0392B", linewidth=2.5, linestyle="--",
        label=r"Dynamic Thermal Limit ($P_{\rm limit}$ @ $T_{\rm out}$)", zorder=12,
    )
    ax1.axhline(
        P_RATED_KW / 1e3, color="#7F8C8D", linewidth=1.5, linestyle=":",
        label=f"Nameplate Rating = {P_RATED_KW/1e3:.1f} MW (20°C)",
    )

    ax2 = ax1.twinx()
    ax1.set_zorder(ax2.get_zorder() + 1)
    ax1.patch.set_visible(False)
    temp_color = PALETTE["outdoor_temp"]
    ax2.plot(
        t_hours, ambient, color=temp_color, linewidth=2.0,
        linestyle="-.", alpha=0.95, zorder=0,
        label=r"$T_{\rm out}$ (°C)",
    )
    ax2.set_ylabel("Outdoor temp. (°C)", color=temp_color, fontsize=13)
    ax2.tick_params(axis="y", labelcolor=temp_color, labelsize=11)
    ax2.spines["right"].set_edgecolor(temp_color)
    ax2.set_ylim(ambient.min() - 2, ambient.max() + 2)

    ax1.set_xlim(0, h_max)
    ax1.set_ylim(bottom=max(0, p_bldg_p5.min() / 1e3 - 1))
    ax1.set_xticks(x_ticks)
    ax1.set_xticklabels(x_labels, fontsize=11)
    ax1.tick_params(axis="y", labelsize=11)
    ax1.set_xlabel("Hour of day", fontsize=13)
    ax1.set_ylabel("Substation load (MW)", fontsize=13)
    ax1.spines["top"].set_visible(False)
    ax1.grid(axis="y", color="#EAEAEA", linewidth=0.8, zorder=0)

    lines1, lb1 = ax1.get_legend_handles_labels()
    lines2, lb2 = ax2.get_legend_handles_labels()
    ax1.legend(
        lines1 + lines2, lb1 + lb2, loc="upper left", fontsize=10, ncol=2,
        frameon=True, framealpha=1.0, facecolor="white", edgecolor="#CCCCCC",
    ).set_zorder(99)

    outpath = OUTPUTS_DIR / "stacked_ev_scenarios.pdf"
    outpath_png = OUTPUTS_DIR / "stacked_ev_scenarios.png"

    fig.tight_layout()
    fig.savefig(outpath, dpi=200, bbox_inches="tight")
    fig.savefig(outpath_png, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {outpath}")
    print(f"  Saved {outpath_png}")


if __name__ == "__main__":
    main()
