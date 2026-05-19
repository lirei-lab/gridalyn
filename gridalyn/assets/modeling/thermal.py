"""Transformer thermal forecast models for grid operation studies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

from gridalyn.assets.datagen.data.weather import download_tmy, select_peak_load_day
from gridalyn.assets.datagen.grid.transformer_thermal import TransformerThermalModel


THERMAL_FORECAST_SOURCE = "TMY peak cold day"
THERMAL_LIMIT_MODEL = "IEEE C57.91 steady-state inverse"
DEFAULT_RESOLUTION_MINUTES = 5
DEFAULT_S_RATED_KVA = 15_000.0
DEFAULT_THETA_MAX_C = 110.0


@dataclass(frozen=True)
class ThermalForecast:
    """Dynamic transformer active-power limit derived from ambient temperature."""

    ambient_c: np.ndarray
    p_limit_kw: np.ndarray
    start_time: str
    resolution_minutes: int
    model: TransformerThermalModel


def build_thermal_forecast_from_ambient(
    ambient_c: Iterable[float],
    *,
    resolution_minutes: int,
    s_rated_kva: float,
    theta_max: float,
    start_time: str,
) -> ThermalForecast:
    """Build a dynamic thermal limit trace from an explicit ambient-temperature trace."""
    ambient = np.asarray(list(ambient_c), dtype=float)
    model = TransformerThermalModel(s_rated_kva=s_rated_kva, theta_max=theta_max)
    p_limit_kw = np.array([model.max_load_for_temp(float(temp_c)) for temp_c in ambient])
    return ThermalForecast(
        ambient_c=ambient,
        p_limit_kw=p_limit_kw,
        start_time=start_time,
        resolution_minutes=int(resolution_minutes),
        model=model,
    )


def build_thermal_forecast(
    n_steps: int,
    resolution_minutes: int = DEFAULT_RESOLUTION_MINUTES,
    *,
    s_rated_kva: float = DEFAULT_S_RATED_KVA,
    theta_max: float = DEFAULT_THETA_MAX_C,
    duration_hours: int = 28,
) -> ThermalForecast:
    """Build an ambient forecast and dynamic transformer limit trace from TMY data."""
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


def thermal_forecast_metadata(
    forecast: ThermalForecast,
    peak_idx: int | None = None,
    peak_label: str | None = None,
    winter_design_limit_mw: float | None = None,
) -> dict[str, float | int | str]:
    """Return stable JSON metadata for a thermal-limit forecast."""
    metadata: dict[str, float | int | str] = {
        "thermal_forecast_source": THERMAL_FORECAST_SOURCE,
        "thermal_forecast_start": forecast.start_time,
        "thermal_forecast_resolution_minutes": int(forecast.resolution_minutes),
        "thermal_model": THERMAL_LIMIT_MODEL,
        "ambient_min_c": float(np.min(forecast.ambient_c)),
        "ambient_max_c": float(np.max(forecast.ambient_c)),
        "ambient_mean_c": float(np.mean(forecast.ambient_c)),
        "dynamic_limit_min_mw": float(np.min(forecast.p_limit_kw) / 1000.0),
        "dynamic_limit_max_mw": float(np.max(forecast.p_limit_kw) / 1000.0),
        "dynamic_limit_mean_mw": float(np.mean(forecast.p_limit_kw) / 1000.0),
    }

    if peak_idx is not None:
        prefix = f"{peak_label}_" if peak_label else ""
        metadata[f"{prefix}dynamic_limit_at_peak_mw"] = float(
            forecast.p_limit_kw[peak_idx] / 1000.0
        )
        metadata[f"{prefix}ambient_at_peak_c"] = float(forecast.ambient_c[peak_idx])

    if winter_design_limit_mw is not None:
        metadata["dynamic_limit_winter_design_mw"] = float(winter_design_limit_mw)

    return metadata
