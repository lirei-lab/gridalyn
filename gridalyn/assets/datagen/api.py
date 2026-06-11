"""One-call helpers for synthetic residential load generation.

These functions compose the lower-level datagen pieces (TMY weather, study-day
selection, and the load engines behind :class:`GridLoadFacade`) into a single
reproducible entry point, plus small shaping helpers that anchor generated
profiles to magnitudes declared in a project contract::

    from gridalyn.assets.datagen import generate_residential_load_profiles

    profiles = generate_residential_load_profiles(
        n_units=50, day="peak", resolution_minutes=15, seed=7,
        weather="synthetic",
    )

Generated profiles carry the SHAPE and DIVERSITY of the synthetic engines;
magnitude anchoring (peaks, totals) stays an explicit, declared decision.
"""

from __future__ import annotations

from typing import Literal, Mapping

import numpy as np
import pandas as pd

from gridalyn.assets.datagen.core import GridLoadFacade, LoadGeneratorType
from gridalyn.assets.datagen.data.weather import (
    WeatherSource,
    download_tmy,
    select_cold_day,
    select_peak_load_day,
)


DayKind = Literal["peak", "cold"]


def generate_residential_load_profiles(
    n_units: int,
    *,
    day: DayKind = "peak",
    duration_hours: int = 24,
    resolution_minutes: int = 15,
    seed: int = 42,
    generator: LoadGeneratorType = "parametric",
    weather: WeatherSource = "auto",
) -> pd.DataFrame:
    """Generate per-unit residential load profiles for one study day.

    Returns a DataFrame in kilowatts with shape ``(time_steps, n_units)``,
    columns ``unit_000 ...``, and a DatetimeIndex at ``resolution_minutes``.
    Deterministic for a fixed ``seed`` when ``weather="synthetic"``.
    """
    if day == "peak":
        window = select_peak_load_day(
            download_tmy(source=weather), duration_hours=duration_hours
        )
    elif day == "cold":
        window = select_cold_day(
            download_tmy(source=weather), duration_hours=duration_hours
        )
    else:
        raise ValueError(f"unknown day kind {day!r}; expected 'peak' or 'cold'")

    temperature = window["temp_air"]
    heat_kw, bg_kw = GridLoadFacade.generate_loads(
        generator_type=generator,
        df_weather=temperature,
        n_houses=n_units,
        resolution_minutes=resolution_minutes,
        seed=seed,
    )
    total_kw = heat_kw + bg_kw
    index = temperature.resample(f"{resolution_minutes}min").mean().index[: len(total_kw)]
    return pd.DataFrame(
        total_kw,
        index=index,
        columns=[f"unit_{i:03d}" for i in range(n_units)],
    )


def aggregate_load_multipliers(
    profiles: pd.DataFrame,
    *,
    intervals: int,
    interval_minutes: int | None = None,
    peak_multiplier: float = 1.0,
    window: Literal["full", "peak"] = "full",
) -> np.ndarray:
    """Reduce per-unit profiles to a normalized aggregate multiplier series.

    Sums across units, bins the aggregate into ``intervals`` values, and
    scales so the maximum equals ``peak_multiplier``. With ``window="peak"``
    (requires ``interval_minutes``) the bins cover the sub-window of length
    ``intervals * interval_minutes`` centred on the coincident peak instead
    of the whole profile.
    """
    if intervals <= 0:
        raise ValueError("intervals must be positive")
    if peak_multiplier <= 0:
        raise ValueError("peak_multiplier must be positive")
    if window not in ("full", "peak"):
        raise ValueError(f"unknown window {window!r}; expected 'full' or 'peak'")

    aggregate = profiles.sum(axis=1)
    if interval_minutes is not None:
        aggregate = (
            aggregate.resample(f"{interval_minutes}min")
            .mean()
            .interpolate("linear")
            .ffill()
            .bfill()
        )

    if window == "peak":
        if interval_minutes is None:
            raise ValueError("window='peak' requires interval_minutes")
        if len(aggregate) < intervals:
            raise ValueError(
                f"profile too short: {len(aggregate)} samples at {interval_minutes}min "
                f"cannot fill a {intervals}-interval peak window; generate a longer "
                "durationHours or a finer resolutionMinutes"
            )
        peak_position = int(np.argmax(aggregate.to_numpy(dtype=float)))
        start = max(0, min(peak_position - intervals // 2, len(aggregate) - intervals))
        binned = aggregate.to_numpy(dtype=float)[start : start + intervals]
    else:
        if len(aggregate) < intervals:
            raise ValueError(
                f"profile too short: {len(aggregate)} samples cannot be binned into "
                f"{intervals} intervals; generate a finer resolutionMinutes"
            )
        bins = np.array_split(aggregate.to_numpy(dtype=float), intervals)
        binned = np.array([bin_values.mean() for bin_values in bins], dtype=float)

    if binned.max() <= 0:
        raise ValueError("aggregate profile has no positive load; cannot normalize")
    return binned * (peak_multiplier / binned.max())


def _group_units_by_key(
    profiles: pd.DataFrame,
    keys: list[int],
) -> dict[int, pd.Series]:
    """Round-robin assign unit columns to keys and aggregate per key (kW)."""
    if not keys:
        raise ValueError("at least one anchor bus is required")
    grouped: dict[int, pd.Series] = {}
    for position, column in enumerate(profiles.columns):
        key = keys[position % len(keys)]
        series = profiles[column]
        grouped[key] = series if key not in grouped else grouped[key] + series
    return grouped


def scale_profiles_to_peaks(
    profiles: pd.DataFrame,
    peaks_mw: Mapping[int, float],
) -> pd.DataFrame:
    """Aggregate generated units per bus and anchor each bus peak to ``peaks_mw``.

    Returns per-bus time series in megawatts whose per-bus maxima equal the
    declared peaks exactly; the time shape and bus diversity come from the
    generated profiles.
    """
    keys = sorted(int(key) for key in peaks_mw)
    grouped = _group_units_by_key(profiles, keys)
    scaled = {}
    for key in keys:
        series_kw = grouped[key]
        peak_kw = float(series_kw.max())
        if peak_kw <= 0:
            raise ValueError(f"generated profile for bus {key} has no positive load")
        scaled[key] = series_kw * (float(peaks_mw[key]) / peak_kw)
    return pd.DataFrame(scaled)


def coincident_peak_loads_mw(
    profiles: pd.DataFrame,
    anchor_loads_mw: Mapping[int, float],
) -> dict[int, float]:
    """Return per-bus loads at the coincident system peak, anchored in total.

    Units are round-robin grouped onto the anchor buses; the row at the
    aggregate peak provides the per-bus shares, rescaled so the system total
    equals ``sum(anchor_loads_mw)``. Use the result as a diversified
    ``loads_mw`` snapshot for a feeder spec.
    """
    keys = sorted(int(key) for key in anchor_loads_mw)
    grouped = _group_units_by_key(profiles, keys)
    per_bus = pd.DataFrame(grouped)
    peak_row = per_bus.loc[per_bus.sum(axis=1).idxmax()]
    total_kw = float(peak_row.sum())
    if total_kw <= 0:
        raise ValueError("generated profiles have no positive coincident load")
    anchor_total_mw = float(sum(anchor_loads_mw.values()))
    return {
        int(key): float(peak_row[key]) * (anchor_total_mw / total_kw)
        for key in keys
    }


__all__ = [
    "DayKind",
    "aggregate_load_multipliers",
    "coincident_peak_loads_mw",
    "generate_residential_load_profiles",
    "scale_profiles_to_peaks",
]
