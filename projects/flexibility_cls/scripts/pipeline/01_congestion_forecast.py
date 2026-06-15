"""
01_congestion_forecast.py

Generates the probabilistic congestion forecast from the same Monte Carlo
profiles used by the CLS project workflow. Static nameplate exceedance and dynamic
IEEE C57.91 thermal-limit exceedance are reported separately.
Outputs: flex_requirements.json, congestion_temporal_bounds.parquet.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.operations.flexibility import build_congestion_forecast
from projects.flexibility_cls.scripts.config import (
    EV_PERCENTAGES,
    N_REALIZATIONS,
    P_RATED_KW,
    RES_MINUTES,
)
from projects.flexibility_cls.scripts.thermal_forecast import (
    build_thermal_forecast,
)

DATA_DIR = ROOT / "projects/flexibility_cls/outputs/data"
OUTPUTS_DIR = ROOT / "projects/flexibility_cls/outputs/json"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


def _load_mc_profiles() -> tuple[pd.DataFrame, pd.DataFrame]:
    b_path = DATA_DIR / "substation_baseline_mc.parquet"
    ev_path = DATA_DIR / "substation_ev_capability_mc.parquet"

    if not b_path.exists() or not ev_path.exists():
        raise FileNotFoundError(
            "Parquet data not found. Run 00_generate_stochastic_profiles.py first."
        )

    return pd.read_parquet(b_path), pd.read_parquet(ev_path)


def main():
    print("=" * 60)
    print("  [Step 1] Congestion Forecast & Target Calculation")
    print("=" * 60)

    df_baseline, df_ev = _load_mc_profiles()
    n_realizations = df_baseline.shape[1]
    if n_realizations != N_REALIZATIONS:
        print(
            f"  [!] Expected {N_REALIZATIONS} MC realizations from config, "
            f"found {n_realizations} in parquet."
        )

    n_steps = df_baseline.shape[0]
    thermal_forecast = build_thermal_forecast(n_steps)
    result = build_congestion_forecast(
        baseline_mw=df_baseline,
        ev_capability_mw=df_ev,
        ev_percentages=EV_PERCENTAGES,
        p_rated_kw=P_RATED_KW,
        resolution_minutes=RES_MINUTES,
        thermal_forecast=thermal_forecast,
        target_ev_percent=20,
    )

    np.save(DATA_DIR / "base_peak_vals.npy", result.base_peak_values_mw)
    np.save(DATA_DIR / "s2_peak_vals.npy", result.target_peak_values_mw)

    with open(OUTPUTS_DIR / "flex_requirements.json", "w") as f:
        json.dump(result.requirements, f, indent=4)

    result.temporal_bounds.to_parquet(
        DATA_DIR / "congestion_temporal_bounds.parquet",
        index=False,
    )

    print(f"  -> Saved dynamic thermal bounds to {OUTPUTS_DIR / 'flex_requirements.json'}")
    print(f"  -> Saved temporal trace limits to {DATA_DIR / 'congestion_temporal_bounds.parquet'}")
    print("  ✓ Step 1 Complete\n")


if __name__ == "__main__":
    main()
