"""Stage: train and cross-validate the heating imputer."""

from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.projects.scripting import project_script
from projects.admm_thermal_consensus.scripts import config as C
from projects.admm_thermal_consensus.scripts.forecast.imputer import HeatingImputer


def main() -> None:
    script = project_script()
    heat = pd.read_parquet(C.DATA_DIR / "agents_heating.parquet").to_numpy()
    params = json.loads((C.JSON_DIR / "agent_params.json").read_text())
    temp = np.asarray(params["temperature_c"], dtype=float)
    levels = heat.mean(axis=1)

    # leave-agents-out CV: 5 folds across agents
    rng = np.random.default_rng(C.SEED)
    order = rng.permutation(C.N_AGENTS)
    folds = np.array_split(order, 5)
    rmses, maes = [], []
    for fold in folds:
        test_idx = np.asarray(fold)
        train_idx = np.array([i for i in range(C.N_AGENTS) if i not in set(test_idx)])
        imp = HeatingImputer(random_seed=C.SEED)
        imp.fit(temp, heat[train_idx], levels[train_idx])
        for i in test_idx:
            pred = imp.predict_agent(temp, float(levels[i]))
            rmses.append(float(np.sqrt(np.mean((pred - heat[i]) ** 2))))
            maes.append(float(np.mean(np.abs(pred - heat[i]))))

    # final model fit on all agents
    final = HeatingImputer(random_seed=C.SEED).fit(temp, heat, levels)
    C.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    model_path = C.CACHE_DIR / "imputer.pkl"
    with open(model_path, "wb") as fh:
        pickle.dump(final, fh)

    cv = {
        "cv_rmse_kw_mean": float(np.mean(rmses)),
        "cv_rmse_kw_std": float(np.std(rmses)),
        "cv_mae_kw_mean": float(np.mean(maes)),
        "heating_std_kw": float(heat.std()),
    }
    cv_path = C.JSON_DIR / "forecast_cv.json"
    cv_path.write_text(json.dumps(cv, indent=2), encoding="utf-8")

    script.write_report(
        "forecast_report",
        artifacts=[script.file_reference(model_path), script.file_reference(cv_path)],
        summary=cv,
    )
    print(f"train_forecaster: CV RMSE {cv['cv_rmse_kw_mean']:.3f} kW")


if __name__ == "__main__":
    main()
