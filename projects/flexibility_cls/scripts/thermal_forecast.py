"""Thermal forecast defaults for the EV capacity limitation project."""

from __future__ import annotations

from gridalyn.assets.modeling.thermal import (
    THERMAL_FORECAST_SOURCE,
    THERMAL_LIMIT_MODEL,
    ThermalForecast,
    build_thermal_forecast as _build_thermal_forecast,
    thermal_forecast_metadata,
)
from projects.flexibility_cls.scripts.config import RES_MINUTES, S_RATED_KVA, THETA_MAX


def build_thermal_forecast(
    n_steps: int,
    resolution_minutes: int = RES_MINUTES,
) -> ThermalForecast:
    """Build the project thermal forecast using study transformer parameters."""
    return _build_thermal_forecast(
        n_steps,
        resolution_minutes=resolution_minutes,
        s_rated_kva=S_RATED_KVA,
        theta_max=THETA_MAX,
    )


__all__ = [
    "THERMAL_FORECAST_SOURCE",
    "THERMAL_LIMIT_MODEL",
    "ThermalForecast",
    "build_thermal_forecast",
    "thermal_forecast_metadata",
]
