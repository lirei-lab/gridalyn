"""Time-series readers for the EV capacity limitation project outputs."""

from __future__ import annotations

from functools import wraps
from pathlib import Path

import numpy as np

from gridalyn.io import timeseries as _timeseries

ROOT = Path(__file__).parents[3]
DATA_DIR = ROOT / "projects" / "flexibility_cls" / "outputs" / "data"


@wraps(_timeseries.get_baseline_building_load)
def get_baseline_building_load(
    percentile: int = 50,
    resolution_minutes: int = 5,
) -> np.ndarray:
    """Return aggregated baseline building load in kW for the project data directory."""
    return _timeseries.get_baseline_building_load(
        percentile=percentile,
        resolution_minutes=resolution_minutes,
        data_dir=DATA_DIR,
    )


@wraps(_timeseries.get_baseline_building_load_all)
def get_baseline_building_load_all() -> np.ndarray:
    """Return baseline building load in kW for all project realizations."""
    return _timeseries.get_baseline_building_load_all(data_dir=DATA_DIR)


@wraps(_timeseries.get_ev_capability_load_all)
def get_ev_capability_load_all() -> np.ndarray:
    """Return EV capability load in kW for all project realizations."""
    return _timeseries.get_ev_capability_load_all(data_dir=DATA_DIR)


@wraps(_timeseries.get_powerflow_ext_grid_load_all)
def get_powerflow_ext_grid_load_all() -> np.ndarray:
    """Return external-grid active power in MW for all project realizations."""
    return _timeseries.get_powerflow_ext_grid_load_all(data_dir=DATA_DIR)


__all__ = [
    "DATA_DIR",
    "get_baseline_building_load",
    "get_baseline_building_load_all",
    "get_ev_capability_load_all",
    "get_powerflow_ext_grid_load_all",
]
