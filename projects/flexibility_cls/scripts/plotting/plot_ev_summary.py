"""Generate EV peak summary figure from project simulation outputs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from projects.flexibility_cls.scripts.config import (  # noqa: E402
    EV_PERCENTAGES,
    P_LIMIT_KW,
    PF,
    S_RATED_KVA,
)

OUTPUTS_DIR = ROOT / "projects" / "flexibility_cls" / "outputs" / "figures" / "02_stage1_stochastic_load"
DATA_DIR = ROOT / "projects" / "flexibility_cls" / "outputs" / "data"
JSON_DIR = ROOT / "projects" / "flexibility_cls" / "outputs" / "json"

PALETTE = {
    "unmanaged": "#E87040",
    "managed": "#27AE60",
    "limit": "#E74C3C",
    "dynamic": "#4A90D9",
}


def main() -> None:
    """Create the scenario peak-load comparison figure."""
    print("=" * 66)
    print("  EV Peak Summary - Two-Stage CLS (Real Simulation Data)")
    print("=" * 66)

    df_mc = pd.read_parquet(DATA_DIR / "substation_baseline_mc.parquet")
    peak_baseline_mw = float(df_mc.mean(axis=1).max())
    static_limit_mw = P_LIMIT_KW / 1000.0
    p_rated_mw = (S_RATED_KVA * PF) / 1000.0

    print(f"  Building baseline peak  : {peak_baseline_mw:.2f} MW")
    print(f"  P_rated (15 MVA x {PF})  : {p_rated_mw:.2f} MW")
    print(f"  Static active limit      : {static_limit_mw:.2f} MW")

    with (JSON_DIR / "ev_summary_results.json").open("r") as f:
        empirical_data = json.load(f)
    dynamic_limit_mw = float(empirical_data["p_limit_dynamic_mw"])
    print(f"  Dynamic theta_H headroom : {dynamic_limit_mw:.2f} MW")

    results = []
    for scenario_index, ev_pct in enumerate(EV_PERCENTAGES):
        scenario_key = f"S{scenario_index}_{ev_pct}pct"
        if scenario_key not in empirical_data:
            continue
        scenario = empirical_data[scenario_key]
        results.append(
            {
                "label": f"S{scenario_index}\n{ev_pct}% EV",
                "ev_pct": ev_pct,
                "n_ev": scenario["n_ev"],
                "unmanaged_mw": scenario["unmanaged_peak_mw"],
                "managed_mw": scenario["managed_peak_mw"],
            }
        )
        print(
            f"  Loaded S{scenario_index}: {ev_pct:2d}% EV ({scenario['n_ev']} EVs)  "
            f"unmanaged={scenario['unmanaged_peak_mw']:.2f} MW  "
            f"managed={scenario['managed_peak_mw']:.2f} MW"
        )

    labels = [row["label"] for row in results]
    unmanaged = [row["unmanaged_mw"] for row in results]
    managed = [row["managed_mw"] for row in results]
    x = np.arange(len(labels))
    width = 0.35

    fig, ax = plt.subplots(figsize=(10.0, 5.5))
    bars_u = ax.bar(
        x - width / 2,
        unmanaged,
        width,
        color=PALETTE["unmanaged"],
        label="Unmanaged Peak",
        alpha=0.88,
        zorder=3,
    )
    bars_m = ax.bar(
        x + width / 2,
        managed,
        width,
        color=PALETTE["managed"],
        label="CLS-Managed Peak",
        alpha=0.88,
        zorder=3,
    )

    for bar in bars_u:
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.08,
            f"{bar.get_height():.2f}",
            ha="center",
            va="bottom",
            fontsize=8.5,
            color=PALETTE["unmanaged"],
        )
    for bar in bars_m:
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + 0.08,
            f"{bar.get_height():.2f}",
            ha="center",
            va="bottom",
            fontsize=8.5,
            color=PALETTE["managed"],
        )

    ax.axhline(
        p_rated_mw,
        color=PALETTE["limit"],
        lw=1.8,
        ls=":",
        label=f"Static $P_{{\\mathrm{{rated}}}}$ = {p_rated_mw:.2f} MW (15 MVA)",
    )
    ax.axhspan(
        p_rated_mw,
        dynamic_limit_mw,
        color=PALETTE["dynamic"],
        alpha=0.08,
        label=f"Dynamic thermal headroom (up to {dynamic_limit_mw:.1f} MW)",
    )

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9.5)
    ax.set_ylabel("Peak Substation Load (MW)", fontsize=11)
    ax.set_xlabel("EV Penetration Scenario", fontsize=11)
    ax.set_ylim(0, max(unmanaged) * 1.15)
    ax.grid(axis="y", alpha=0.35, lw=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.legend(
        loc="upper left",
        frameon=True,
        framealpha=1.0,
        facecolor="white",
        edgecolor="#CCCCCC",
        fontsize=9,
    ).set_zorder(10)

    fig.tight_layout()
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    out_pdf = OUTPUTS_DIR / "load_management.pdf"
    out_png = OUTPUTS_DIR / "load_management.png"
    fig.savefig(out_pdf, dpi=200, bbox_inches="tight")
    fig.savefig(out_png, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"\n  Saved {out_pdf}")
    print(f"  Saved {out_png}")


if __name__ == "__main__":
    main()
