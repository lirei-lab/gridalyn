"""Stage: consolidate KPIs + network feasibility into the governed study report."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.projects.scripting import project_script
from projects.admm_thermal_consensus.scripts import config as C


def main() -> None:
    script = project_script()
    kpis = json.loads((C.JSON_DIR / "aggregate_kpis.json").read_text())
    cv = json.loads((C.JSON_DIR / "forecast_cv.json").read_text())
    feas = pd.read_parquet(C.DATA_DIR / "network_feasibility.parquet")

    results = {
        "aggregate_kpis": kpis,
        "forecast_cv": cv,
        "network_feasibility": feas.to_dict(orient="records"),
        "config": {
            "n_agents": C.N_AGENTS,
            "n_steps": C.N_STEPS,
            "rho_sweep": list(C.RHO_SWEEP),
            "deferrability_alpha": C.DEFERRABILITY_ALPHA,
            "target_feeder_peak_mw": C.TARGET_FEEDER_PEAK_MW,
        },
    }
    C.JSON_DIR.mkdir(parents=True, exist_ok=True)
    results_path = C.JSON_DIR / "study_results.json"
    results_path.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")

    script.write_report(
        "study_report",
        artifacts=[script.file_reference(results_path)],
        summary={
            "ideal_peak_reduction_fraction": 1
            - kpis["coordinated_ideal"]["peak_kw"] / kpis["uncoordinated"]["peak_kw"],
            "cv_rmse_kw_mean": cv["cv_rmse_kw_mean"],
            "n_scenarios": int(len(feas)),
        },
    )
    print("build_study_report: study_results.json written")


if __name__ == "__main__":
    main()
