"""Parquet readers for project time-series artifacts."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

BASELINE_MC_FILE = "substation_baseline_mc.parquet"
POWERFLOW_MC_FILE = "substation_powerflow_mc.parquet"


def _require_parquet(data_dir: Path, filename: str, hint: str) -> Path:
    path = Path(data_dir) / filename
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}. {hint}")
    return path


def get_baseline_building_load(
    percentile: int = 50,
    resolution_minutes: int = 5,
    *,
    data_dir: Path,
) -> np.ndarray:
    """Return aggregated baseline building load in kW for the requested percentile."""
    del resolution_minutes
    path = _require_parquet(
        Path(data_dir),
        BASELINE_MC_FILE,
        "Run the workflow stage that generates stochastic baseline profiles first.",
    )
    frame = pd.read_parquet(path)
    if percentile == 50:
        return frame.median(axis=1).to_numpy() * 1000.0
    return np.percentile(frame.to_numpy(), percentile, axis=1) * 1000.0


def get_baseline_building_load_all(*, data_dir: Path) -> np.ndarray:
    """Return baseline building load in kW for every realization."""
    path = _require_parquet(
        Path(data_dir),
        BASELINE_MC_FILE,
        "Run the workflow stage that generates stochastic baseline profiles first.",
    )
    return pd.read_parquet(path).to_numpy().T * 1000.0


def get_powerflow_ext_grid_load_all(*, data_dir: Path) -> np.ndarray:
    """Return external-grid active power in MW for every realization."""
    path = _require_parquet(
        Path(data_dir),
        POWERFLOW_MC_FILE,
        "Run the workflow stage that generates powerflow Monte Carlo profiles first.",
    )
    return pd.read_parquet(path).to_numpy().T
