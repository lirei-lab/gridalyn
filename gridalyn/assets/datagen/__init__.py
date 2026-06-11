"""Experimental data-generation helpers for synthetic grid studies.

The stable public asset-modeling API lives in :mod:`gridalyn.assets`. This
subpackage exposes lower-level stochastic load, weather, and MV-network helpers
used by examples and advanced project workflows. Treat these objects as
reproducible synthetic baselines, not calibrated utility production models.
"""

from __future__ import annotations

from importlib import import_module

_LAZY_EXPORTS = {
    "Feeder": ("gridalyn.assets.datagen.grid.network", "Feeder"),
    "GridLoadFacade": ("gridalyn.assets.datagen.core", "GridLoadFacade"),
    "aggregate_load_multipliers": (
        "gridalyn.assets.datagen.api",
        "aggregate_load_multipliers",
    ),
    "coincident_peak_loads_mw": (
        "gridalyn.assets.datagen.api",
        "coincident_peak_loads_mw",
    ),
    "generate_residential_load_profiles": (
        "gridalyn.assets.datagen.api",
        "generate_residential_load_profiles",
    ),
    "scale_profiles_to_peaks": (
        "gridalyn.assets.datagen.api",
        "scale_profiles_to_peaks",
    ),
    "MVNetwork": ("gridalyn.assets.datagen.grid.network", "MVNetwork"),
    "MVNetworkConfig": ("gridalyn.assets.datagen.grid.network", "MVNetworkConfig"),
    "ParametricArxGenerator": (
        "gridalyn.assets.datagen.load_profiles",
        "ParametricArxGenerator",
    ),
    "build_thermal_forecast": ("gridalyn.assets.datagen.thermal", "build_thermal_forecast"),
    "download_tmy": ("gridalyn.assets.datagen.data.weather", "download_tmy"),
    "load_mv_network_config": (
        "gridalyn.assets.datagen.grid.network",
        "load_mv_network_config",
    ),
    "select_cold_day": ("gridalyn.assets.datagen.data.weather", "select_cold_day"),
    "select_peak_load_day": (
        "gridalyn.assets.datagen.data.weather",
        "select_peak_load_day",
    ),
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str):
    if name in _LAZY_EXPORTS:
        module_name, attr_name = _LAZY_EXPORTS[name]
        value = getattr(import_module(module_name), attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'gridalyn.assets.datagen' has no attribute {name!r}")
