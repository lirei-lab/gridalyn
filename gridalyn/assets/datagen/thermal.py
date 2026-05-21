"""Synthetic thermal-forecast generators for asset models."""

from __future__ import annotations

from gridalyn.assets.datagen.data.weather import download_tmy, select_peak_load_day
from gridalyn.assets.modeling.thermal import (
    DEFAULT_S_RATED_KVA,
    DEFAULT_THETA_MAX_C,
    ThermalForecast,
    build_thermal_forecast_from_ambient,
)


DEFAULT_RESOLUTION_MINUTES = 5


def build_thermal_forecast(
    n_steps: int,
    resolution_minutes: int = DEFAULT_RESOLUTION_MINUTES,
    *,
    s_rated_kva: float = DEFAULT_S_RATED_KVA,
    theta_max: float = DEFAULT_THETA_MAX_C,
    duration_hours: int = 28,
) -> ThermalForecast:
    """Build a synthetic ambient forecast and transformer limit trace from TMY data."""
    tmy = download_tmy()
    cold_day = select_peak_load_day(tmy, duration_hours=duration_hours)
    ambient_c = (
        cold_day["temp_air"]
        .resample(f"{resolution_minutes}min")
        .interpolate()
        .values[:n_steps]
        .astype(float)
    )
    return build_thermal_forecast_from_ambient(
        ambient_c,
        resolution_minutes=resolution_minutes,
        s_rated_kva=s_rated_kva,
        theta_max=theta_max,
        start_time=str(cold_day.index.min()),
    )


__all__ = ["DEFAULT_RESOLUTION_MINUTES", "build_thermal_forecast"]
