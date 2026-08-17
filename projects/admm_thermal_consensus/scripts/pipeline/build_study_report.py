"""Stage: consolidate KPIs + network feasibility into the governed study report."""

from __future__ import annotations

import pandas as pd

from gridalyn.projects.scripting import project_script
from projects.admm_thermal_consensus.scripts import config as C


def main() -> None:
    script = project_script()
    kpis = script.read_json("outputs/json/aggregate_kpis.json")
    cv = script.read_json("outputs/json/forecast_cv.json")
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
            "transformer_kva": C.TRANSFORMER_KVA,
        },
    }
    results_path = script.write_json("outputs/json/study_results.json", results)

    script.write_report(
        "study_report",
        artifacts=[results_path],
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
