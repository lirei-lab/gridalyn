"""Stage: render paper figures from the study artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.projects.scripting import project_script  # configures headless Agg
from projects.admm_thermal_consensus.scripts import config as C


def _save(fig, stem: str) -> list[Path]:
    C.FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    paths = [C.FIGURES_DIR / f"{stem}.png", C.FIGURES_DIR / f"{stem}.pdf"]
    for p in paths:
        fig.savefig(p, bbox_inches="tight", dpi=200)
    return paths


def main() -> None:
    script = project_script()
    import matplotlib.pyplot as plt

    profiles = pd.read_parquet(C.DATA_DIR / "aggregate_profiles.parquet")
    kpis = json.loads((C.JSON_DIR / "aggregate_kpis.json").read_text())
    feas = pd.read_parquet(C.DATA_DIR / "network_feasibility.parquet")
    hours = np.arange(C.N_STEPS) * C.STEP_HOURS

    # Fig 1: aggregate load profiles (uncoordinated vs ideal vs worst imputed)
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(hours, profiles["uncoordinated"], label="Uncoordinated", lw=2)
    ax.plot(hours, profiles["coordinated_ideal"], label="ADMM (ideal comms)", lw=2)
    worst_key = f"imputed_rho_{int(round(C.ILLUSTRATIVE_RHO * 100)):03d}"
    ax.plot(hours, profiles[worst_key], "--", label=f"ADMM (rho={C.ILLUSTRATIVE_RHO})", lw=2)
    ax.set_xlabel("Hour of cold day")
    ax.set_ylabel("Aggregate load [kW]")
    ax.legend()
    ax.grid(alpha=0.3)
    f1 = _save(fig, "fig_aggregate_profiles")
    plt.close(fig)

    # Fig 2: peak & PAR vs rho
    rhos = list(C.RHO_SWEEP)
    peaks = [kpis[f"imputed_rho_{int(round(r * 100)):03d}"]["peak_kw"] for r in rhos]
    pars = [kpis[f"imputed_rho_{int(round(r * 100)):03d}"]["par"] for r in rhos]
    fig, ax1 = plt.subplots(figsize=(7, 4))
    ax1.plot(rhos, peaks, "o-", color="tab:red", label="Peak [kW]")
    ax1.axhline(kpis["uncoordinated"]["peak_kw"], ls=":", color="gray", label="Uncoordinated peak")
    ax1.set_xlabel("Non-responsive fraction rho")
    ax1.set_ylabel("Peak [kW]")
    ax2 = ax1.twinx()
    ax2.plot(rhos, pars, "s--", color="tab:blue", label="PAR")
    ax2.set_ylabel("PAR")
    ax1.legend(loc="upper left")
    f2 = _save(fig, "fig_peak_par_vs_rho")
    plt.close(fig)

    # Fig 3: network violation severity vs rho (HEADLINE)
    imp = feas[feas.scenario.str.startswith("imputed")].copy()
    imp["rho"] = imp["scenario"].str.extract(r"(\d+)").astype(int) / 100.0
    imp = imp.sort_values("rho")
    fig, ax1 = plt.subplots(figsize=(7, 4))
    ax1.plot(imp["rho"], imp["worst_min_voltage_pu"], "o-", color="tab:green", label="Min voltage [p.u.]")
    ax1.axhline(C.VOLTAGE_LOWER_PU, ls=":", color="gray", label=f"{C.VOLTAGE_LOWER_PU} p.u. limit")
    ax1.set_xlabel("Non-responsive fraction rho")
    ax1.set_ylabel("Worst min voltage [p.u.]")
    ax2 = ax1.twinx()
    ax2.plot(imp["rho"], imp["worst_transformer_loading_pct"], "s--", color="tab:red", label="Transformer loading [%]")
    ax2.axhline(C.TRANSFORMER_LOADING_LIMIT_PCT, ls="--", color="tab:red", alpha=0.4)
    ax2.set_ylabel("Worst transformer loading [%]")
    ax1.legend(loc="lower left")
    f3 = _save(fig, "fig_network_violation_vs_rho")
    plt.close(fig)

    # backing CSVs
    profiles.assign(hour=hours).to_csv(C.FIGURES_DIR / "aggregate_profiles.csv", index=False)
    pd.DataFrame({"rho": rhos, "peak_kw": peaks, "par": pars}).to_csv(
        C.FIGURES_DIR / "peak_par_vs_rho.csv", index=False
    )
    imp.to_csv(C.FIGURES_DIR / "network_violation_vs_rho.csv", index=False)

    all_figs = [*f1, *f2, *f3]
    script.write_report(
        "figures_report",
        artifacts=[script.file_reference(p) for p in all_figs],
        summary={"n_figures": 3, "figure_dir": str(C.FIGURES_DIR)},
    )
    print(f"make_figures: wrote {len(all_figs)} figure files")


if __name__ == "__main__":
    main()
