import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.interfaces import apply_hour_axis, save_figure_pair, style_timeseries_axis
from gridalyn.operations import prepare_cls_market_replay_context
from projects.flexibility_cls.scripts.config import (
    P_LIMIT_KW,
    RES_MINUTES,
    S_RATED_KVA,
    THETA_MAX,
)
from projects.flexibility_cls.scripts.thermal_forecast import build_thermal_forecast

PALETTE = {
    "buildings": "#3498db",  # Blue
    "evs_mean": "#e67e22",  # Orange
    "evs_worst": "#d35400",  # Darker orange
    "soft_cls_contract": "#27ae60",  # Dark Green
    "hard_cls_expected": "#8e44ad",  # Purple
    "thermal_limit": "#c0392b",  # Red
}


def main():
    print("Generating Stage 1: Day-Ahead Dimensioning Plot...")

    data_dir = ROOT / "projects/flexibility_cls/outputs/data"
    out_dir = (
        ROOT / "projects/flexibility_cls/outputs/figures/04_stage3_market_clearing"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load stochastic data
    df_base = pd.read_parquet(data_dir / "substation_baseline_mc.parquet")
    df_ev = pd.read_parquet(data_dir / "substation_ev_capability_mc.parquet")

    context = prepare_cls_market_replay_context(
        baseline_mw=df_base,
        ev_capability_mw=df_ev,
        thermal_forecast=build_thermal_forecast(len(df_base.index)),
        ev_percent=40.0,
        resolution_minutes=RES_MINUTES,
        s_rated_kva=S_RATED_KVA,
        p_limit_kw=P_LIMIT_KW,
        theta_max=THETA_MAX,
        n_feeder_blocks=160,
        participation_rate=0.30,
        market_resolution_h=0.5,
    )
    p_base_kw_mean = context.p_base_kw_mean
    p_ev_kw_mean = context.p_ev_kw_mean
    dt_h = context.dt_h

    # Run the engine (Standard statistical mode to get contracts)
    df_res = context.run(is_profiled=False)

    t_hours = context.t_hours

    p_tot_mean = df_res["p_tot_mean_kw"].values / 1000.0
    p_tot_std = df_res["p_tot_std_kw"].values / 1000.0

    p_limit = context.p_limit_mw

    contracted_soft_mw = df_res["contracted_soft_kw"].values / 1000.0

    from scipy.stats import norm

    z_score = norm.ppf(1 - 0.05)
    p_worst = p_tot_mean + z_score * p_tot_std

    # Create plot
    fig, ax = plt.subplots(figsize=(14, 7))

    # Plot expected unmanaged load
    ax.plot(
        t_hours,
        p_tot_mean,
        color="black",
        lw=2,
        label=r"Expected Unmanaged Load ($\mu$)",
    )

    # Plot worst case
    ax.plot(
        t_hours,
        p_worst,
        color=PALETTE["evs_worst"],
        lw=2,
        ls="--",
        label=r"95th Pct. Worst-Case Envelope ($\mu + Z \cdot \sigma$)",
    )
    ax.fill_between(
        t_hours, p_tot_mean, p_worst, color=PALETTE["evs_worst"], alpha=0.2, hatch="//"
    )

    # Dynamic Limit
    ax.plot(
        t_hours,
        p_limit,
        color=PALETTE["thermal_limit"],
        lw=3,
        ls="-",
        label=r"Dynamic Thermal Limit ($\theta_H$)",
    )

    # Expected Activations for visualization
    expected_soft_act_mw = np.minimum(
        contracted_soft_mw, np.maximum(0, p_worst - p_limit)
    )
    expected_hard_act_mw = np.maximum(0, p_worst - p_limit - expected_soft_act_mw)

    # Plot Soft-CLS Expected Activation
    ax.fill_between(
        t_hours,
        p_worst - expected_soft_act_mw,
        p_worst,
        where=(expected_soft_act_mw > 0),
        color=PALETTE["soft_cls_contract"],
        alpha=0.8,
        label="Soft-CLS: Firm Contracted Capacity",
    )
    soft_cls_patch = None

    # Plot Hard-CLS Expected Activation
    ax.fill_between(
        t_hours,
        p_worst - expected_soft_act_mw - expected_hard_act_mw,
        p_worst - expected_soft_act_mw,
        where=(expected_hard_act_mw > 0),
        color=PALETTE["hard_cls_expected"],
        alpha=0.6,
        label="Hard-CLS: Expected Interruptible Recourse",
    )

    # Plot Expected Rebound — directly from the engine (already thermally clamped)
    p_rebound_mw = df_res["rebound_kw"].values / 1000.0

    if np.max(p_rebound_mw) > 0:
        ax.fill_between(
            t_hours,
            p_tot_mean,
            p_tot_mean + p_rebound_mw,
            where=(p_rebound_mw > 0.001),
            color="#D9534F",
            alpha=0.8,
            hatch="\\\\",
            label="Expected Post-Congestion Rebound",
        )

    # Formatting
    ax.set_ylabel("Substation Power Demand [MW]", fontsize=14)

    ax.set_title(
        "First-Stage Stochastic Programming: Day-Ahead Capacity Option",
        fontsize=18,
        weight="bold",
    )

    ax.set_ylim(np.min(p_tot_mean) * 0.8, np.max(p_worst) * 1.1)
    apply_hour_axis(ax, start=0, end=28, step=4, fontsize=14)
    style_timeseries_axis(ax)

    handles, labels = ax.get_legend_handles_labels()
    if soft_cls_patch is not None:
        handles.insert(3, soft_cls_patch)  # Insert after thermal limit roughly
        labels.insert(3, soft_cls_patch.get_label())

    ax.legend(
        handles=handles, labels=labels, loc="upper left", fontsize=12, framealpha=0.9
    )

    plt.tight_layout()

    paths = save_figure_pair(fig, out_dir / "plot_14_stage_1_day_ahead.png")
    print(f"Saved PDF to {paths['pdf']}")
    print(f"Saved to {paths['png']}")


if __name__ == "__main__":
    main()
