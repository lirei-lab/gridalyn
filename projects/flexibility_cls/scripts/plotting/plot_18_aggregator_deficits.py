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


def main():
    data_dir = ROOT / "projects/flexibility_cls/outputs/data"
    out_dir = (
        ROOT / "projects/flexibility_cls/outputs/figures/05_stage4_realtime_dispatch"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    df_base = pd.read_parquet(data_dir / "substation_baseline_mc.parquet")
    df_ev = pd.read_parquet(data_dir / "substation_ev_capability_mc.parquet")

    context = prepare_cls_market_replay_context(
        baseline_mw=df_base,
        ev_capability_mw=df_ev,
        thermal_forecast=build_thermal_forecast(len(df_base.index)),
        ev_percent=30.0,
        resolution_minutes=RES_MINUTES,
        s_rated_kva=S_RATED_KVA,
        p_limit_kw=P_LIMIT_KW,
        theta_max=THETA_MAX,
        n_feeder_blocks=160,
        participation_rate=0.30,
        market_resolution_h=0.5,
    )

    # Run the simulation
    df_res = context.run(is_profiled=True)

    t_hours = context.t_hours

    # Extract deficit columns
    deficit_cols = [c for c in df_res.columns if c.startswith("deficit_")]

    fig, ax = plt.subplots(figsize=(14, 7))

    cmap = plt.get_cmap("viridis")

    colors = cmap(np.linspace(0, 1, len(deficit_cols)))

    for i, col in enumerate(deficit_cols):
        ax.plot(
            t_hours,
            df_res[col].values,
            color=colors[i],
            lw=2,
            alpha=0.8,
            label=f"Aggregator {col.split('_')[1]}",
        )

    ax.set_ylabel("Accumulated Thermal Deficit [kWh]", fontsize=14)

    ax.set_title(
        "Aggregator Thermal Deficit Trajectories (Profiled Dimensioning)",
        fontsize=18,
        weight="bold",
    )

    apply_hour_axis(ax, start=0, end=28, step=4, fontsize=14)
    style_timeseries_axis(ax)

    # Only show a subset of legends if there are too many
    handles, labels = ax.get_legend_handles_labels()
    if len(handles) > 8:
        subset_indices = np.linspace(0, len(handles) - 1, 8, dtype=int)
        ax.legend(
            [handles[i] for i in subset_indices],
            [labels[i] for i in subset_indices],
            loc="upper left",
            fontsize=12,
            framealpha=0.9,
            title="Sample Aggregators",
        )
    else:
        ax.legend(loc="upper left", fontsize=12, framealpha=0.9)

    plt.tight_layout()

    paths = save_figure_pair(fig, out_dir / "plot_18_aggregator_deficits.png")
    print(f"Saved PDF to {paths['pdf']}")
    print(f"Saved to {paths['png']}")


if __name__ == "__main__":
    main()
