"""Stage: render the forecast-uncertainty figure (loading band + P(violation))."""

from __future__ import annotations

import pandas as pd

from gridalyn.projects.scripting import project_script  # configures headless Agg
from projects.admm_thermal_consensus.scripts import config as C


def main() -> None:
    script = project_script()
    import matplotlib.pyplot as plt

    d = pd.read_parquet(C.DATA_DIR / "uncertainty_summary.parquet").sort_values(
        "non_responsive_fraction"
    )
    rho = d["non_responsive_fraction"].to_numpy()

    fig, ax1 = plt.subplots(figsize=(7, 4))
    ax1.fill_between(
        rho,
        d["line_loading_pct_p05"],
        d["line_loading_pct_p95"],
        color="tab:red",
        alpha=0.2,
        label="Transformer loading P5-P95",
    )
    ax1.plot(
        rho,
        d["line_loading_pct_mean"],
        "o-",
        color="tab:red",
        label="Transformer loading mean",
    )
    ax1.axhline(
        C.LINE_LOADING_LIMIT_PCT,
        ls="--",
        color="black",
        alpha=0.6,
        label=f"{C.LINE_LOADING_LIMIT_PCT:.0f}% limit",
    )
    ax1.set_xlabel(r"Non-responsive fraction $\varrho$ (forecast-imputed)")
    ax1.set_ylabel("Worst transformer loading [%]")

    ax2 = ax1.twinx()
    ax2.plot(
        rho,
        d["prob_line_violation"],
        "s--",
        color="tab:blue",
        alpha=0.85,
        markersize=5,
        label="P(transformer violation)",
    )
    ax2.set_ylabel("P(transformer violation)")
    ax2.set_ylim(-0.02, 1.05)

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=8)

    C.FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    paths = [
        C.FIGURES_DIR / "fig_uncertainty_loading.png",
        C.FIGURES_DIR / "fig_uncertainty_loading.pdf",
    ]
    for p in paths:
        fig.savefig(p, bbox_inches="tight", dpi=200)
    plt.close(fig)

    d.to_csv(C.FIGURES_DIR / "uncertainty_summary.csv", index=False)

    script.write_report(
        "uncertainty_figure_report",
        artifacts=[script.file_reference(p) for p in paths],
        summary={"n_figures": 1},
    )
    print(f"make_uncertainty_figure: wrote {len(paths)} figure files")


if __name__ == "__main__":
    main()
