"""Stage: render the imputation-method comparison figure (realized loading vs rho)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.projects.scripting import project_script  # configures headless Agg
from projects.admm_thermal_consensus.scripts import config as C

STYLE = {
    "none": ("No imputation", "tab:red", "o-"),
    "mean_level": ("Mean-level (naive)", "tab:orange", "s-"),
    "lightgbm": ("LightGBM", "tab:blue", "^-"),
    "random_forest": ("Random forest", "tab:green", "v-"),
    "ridge": ("Ridge", "tab:purple", "d-"),
    "knn": ("k-NN", "tab:brown", "*-"),
}


def main() -> None:
    script = project_script()
    import matplotlib.pyplot as plt

    d = pd.read_parquet(C.DATA_DIR / "imputer_comparison_curves.parquet")
    meta = json.loads((C.JSON_DIR / "imputer_comparison.json").read_text())

    fig, ax = plt.subplots(figsize=(7, 4.2))
    for method, (label, color, style) in STYLE.items():
        sub = d[d.method == method].sort_values("rho")
        lw = 2.4 if method == "none" else 1.8
        ax.plot(sub["rho"], sub["loading_pct"], style, color=color, label=label,
                lw=lw, ms=5)
    ax.axhline(C.LINE_LOADING_LIMIT_PCT, ls="--", color="black", alpha=0.6,
               label="100% thermal limit")
    ax.set_xlabel("Non-responsive fraction (silent homes)")
    ax.set_ylabel("Realized worst transformer loading [%]")
    ax.legend(fontsize=8, ncol=2)
    ax.grid(alpha=0.3)

    C.FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    paths = [
        C.FIGURES_DIR / "fig_imputer_comparison.png",
        C.FIGURES_DIR / "fig_imputer_comparison.pdf",
    ]
    for p in paths:
        fig.savefig(p, bbox_inches="tight", dpi=200)
    plt.close(fig)
    d.to_csv(C.FIGURES_DIR / "imputer_comparison_curves.csv", index=False)

    # compact intrinsic-vs-downstream CSV for the paper table
    intr = meta["intrinsic_cv"]; mc = meta["monte_carlo_rep"]
    rows = []
    for m in meta["methods"]:
        rows.append({
            "method": meta["display_names"][m],
            "cv_rmse_kw": intr.get(m, {}).get("rmse_kw"),
            "cv_mae_kw": intr.get(m, {}).get("mae_kw"),
            "cv_r2": intr.get(m, {}).get("r2"),
            "realized_peak_kw": mc[m]["realized_peak_kw_mean"],
            "realized_loading_pct": mc[m]["realized_loading_pct_mean"],
        })
    pd.DataFrame(rows).to_csv(C.FIGURES_DIR / "imputer_comparison_summary.csv", index=False)

    script.write_report(
        "imputer_comparison_figure_report",
        artifacts=[script.file_reference(p) for p in paths],
        summary={"n_figures": 1, "methods": meta["methods"]},
    )
    print(f"make_comparison_figure: wrote {len(paths)} figure files")


if __name__ == "__main__":
    main()
