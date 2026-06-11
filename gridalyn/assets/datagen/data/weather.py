"""
weather.py - Download TMY data for Trois-Rivieres, QC and extract study days.

Uses pvlib.iotools.get_pvgis_tmy() (PVGIS SARAH-3 dataset).
Falls back to a synthetic offline profile if PVGIS is unreachable.

Caching
-------
The first successful download (or synthetic generation) is stored as a versioned
pickle under the generated cache directory and reused on subsequent calls. Set
GRIDALYN_DATAGEN_CACHE_DIR to override the default cache location. Pass
force_refresh=True to bypass the cache and re-fetch from PVGIS.
"""

from __future__ import annotations

import os
import pickle
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
import pvlib


WeatherSource = Literal["auto", "pvgis", "synthetic"]

# Trois-Rivières, QC  (WMO 717200)
LAT = 46.35
LON = -72.55
ALT = 5  # metres ASL

PVGIS_MONTHS = list(range(1, 13))  # full year

REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_CACHE_DIR = REPO_ROOT / "examples" / "generated" / "cache"
_CACHE_DIR = Path(os.environ.get("GRIDALYN_DATAGEN_CACHE_DIR", _DEFAULT_CACHE_DIR))
_CACHE_FILE = _CACHE_DIR / "tmy_trois_rivieres.pkl"
_CACHE_SCHEMA_VERSION = 3
_SOURCE_ATTR = "gridalyn_weather_source"
_SCHEMA_ATTR = "gridalyn_weather_schema_version"
_MIN_REASONABLE_TEMP_C = -45.0
_MAX_REASONABLE_TEMP_C = 45.0


def download_tmy(
    force_refresh: bool = False,
    *,
    source: WeatherSource = "auto",
) -> pd.DataFrame:
    """
    Return an 8760-row DataFrame with columns including 'temp_air' (°C)
    and a DatetimeIndex in local standard time (UTC-5).

    The result is cached on disk after the first call. Subsequent calls
    load from cache instantly without hitting the network.

    Parameters
    ----------
    force_refresh : if True, ignore any existing cache and re-download.
    source : weather data source.
        - ``"auto"`` (default): PVGIS download with synthetic fallback, cached.
        - ``"synthetic"``: always return the deterministic synthetic profile;
          no network access and no cache read/write. Use this when results
          must be byte-stable across environments (projects, CI).
        - ``"pvgis"``: PVGIS download; raises instead of silently falling
          back to the synthetic profile.
    """
    if source not in ("auto", "pvgis", "synthetic"):
        raise ValueError(
            f"unknown weather source {source!r}; expected 'auto', 'pvgis', or 'synthetic'"
        )
    if source == "synthetic":
        return _synthetic_winter_tmy()

    if not force_refresh and _CACHE_FILE.exists():
        print(f"  Loading TMY from cache ({_CACHE_FILE.name}) …")
        with open(_CACHE_FILE, "rb") as f:
            cached_tmy = pickle.load(f)
        if _is_valid_cached_tmy(cached_tmy):
            return cached_tmy
        print("  Cached TMY is legacy or outside expected temperature bounds; refreshing …")

    print("Fetching TMY data from PVGIS for Trois-Rivières …")
    try:
        data, metadata = pvlib.iotools.get_pvgis_tmy(
            latitude=LAT,
            longitude=LON,
            outputformat="json",
            usehorizon=True,
            startyear=2005,
            endyear=2020,
        )
        tmy = data
        tmy.index = tmy.index.tz_convert("America/Toronto")
        _annotate_tmy(tmy, source="pvgis_sarah3")
        print(f"  TMY fetched: {len(tmy)} rows, index tz={tmy.index.tz}")
    except Exception as exc:
        if source == "pvgis":
            raise RuntimeError(
                f"PVGIS download failed and source='pvgis' forbids the synthetic fallback: {exc}"
            ) from exc
        print(f"  PVGIS unavailable ({exc}), generating synthetic winter profile …")
        tmy = _synthetic_winter_tmy()

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(_CACHE_FILE, "wb") as f:
        pickle.dump(tmy, f)
    print(f"  TMY cached to {_CACHE_FILE.name}")
    return tmy


def _annotate_tmy(tmy: pd.DataFrame, *, source: str) -> pd.DataFrame:
    tmy.attrs[_SOURCE_ATTR] = source
    tmy.attrs[_SCHEMA_ATTR] = _CACHE_SCHEMA_VERSION
    tmy.attrs["gridalyn_weather_location"] = {
        "name": "Trois-Rivieres, QC",
        "latitude": LAT,
        "longitude": LON,
    }
    return tmy


def _is_valid_cached_tmy(tmy: object) -> bool:
    if not isinstance(tmy, pd.DataFrame):
        return False
    if tmy.attrs.get(_SCHEMA_ATTR) != _CACHE_SCHEMA_VERSION:
        return False
    if "temp_air" not in tmy.columns or len(tmy) < 8760:
        return False

    temp = pd.to_numeric(tmy["temp_air"], errors="coerce")
    if temp.isna().any():
        return False
    return bool(
        temp.min() >= _MIN_REASONABLE_TEMP_C
        and temp.max() <= _MAX_REASONABLE_TEMP_C
    )


def _synthetic_winter_tmy() -> pd.DataFrame:
    """
    Synthetic TMY based on Trois-Rivières climate normals (1991-2020).
    Monthly mean temperatures (°C): Jan -12.1, Feb -10.6, Mar -4.1,
    Apr 5.0, May 12.0, Jun 17.5, Jul 20.2, Aug 19.4, Sep 13.8,
    Oct 7.2, Nov 0.8, Dec -8.5
    """
    monthly_mean = {
        1: -12.1, 2: -10.6, 3: -4.1, 4: 5.0,
        5: 12.0, 6: 17.5, 7: 20.2, 8: 19.4,
        9: 13.8, 10: 7.2, 11: 0.8, 12: -8.5,
    }
    rng = pd.date_range("2023-01-01", periods=8760, freq="h", tz="America/Toronto")
    rng_gen = np.random.default_rng(42)

    midpoint_index = pd.DatetimeIndex(
        [pd.Timestamp(2022, 12, 15, tz="America/Toronto")]
        + [pd.Timestamp(2023, month, 15, tz="America/Toronto") for month in range(1, 13)]
        + [pd.Timestamp(2024, 1, 15, tz="America/Toronto")]
    )
    midpoint_values = np.array(
        [monthly_mean[12]]
        + [monthly_mean[month] for month in range(1, 13)]
        + [monthly_mean[1]],
        dtype=float,
    )
    base = np.interp(
        rng.view("int64"),
        midpoint_index.view("int64"),
        midpoint_values,
    )
    hour = np.array([ts.hour for ts in rng], dtype=float)
    diurnal = 3.5 * np.cos(2 * np.pi * (hour - 14.0) / 24.0)

    synoptic = np.zeros(len(rng), dtype=float)
    for i in range(1, len(rng)):
        month = rng[i].month
        innovation_sigma = 0.55 if month in {11, 12, 1, 2, 3} else 0.35
        synoptic[i] = 0.975 * synoptic[i - 1] + rng_gen.normal(0.0, innovation_sigma)

    cold_snap = np.zeros(len(rng), dtype=float)
    winter_positions = np.where(np.isin([ts.month for ts in rng], [12, 1, 2]))[0]
    starts = rng_gen.choice(winter_positions[:-72], size=5, replace=False)
    pulse = np.hanning(72)
    for start in starts:
        intensity = rng_gen.uniform(5.0, 11.0)
        cold_snap[start : start + 72] -= intensity * pulse

    temps = np.clip(
        base + diurnal + synoptic + cold_snap,
        _MIN_REASONABLE_TEMP_C + 6.0,
        _MAX_REASONABLE_TEMP_C - 8.0,
    )

    df = pd.DataFrame({"temp_air": temps}, index=rng)
    df["ghi"] = 0.0  # not needed for thermal simulation
    return _annotate_tmy(df, source="synthetic_climate_normals")


def select_cold_day(tmy: pd.DataFrame, month_range: tuple[int, int] = (11, 3), duration_hours: int = 24) -> pd.DataFrame:
    """
    Return a DataFrame (1-minute resolution) for the coldest day over the specified duration.

    Parameters
    ----------
    month_range : (start_month, end_month) inclusive for winter selection.
                  Wraps around year-end (e.g. (11, 3) = Nov–Mar).
    duration_hours : number of hours to extract starting from midnight of the coldest day.
    """
    lo, hi = month_range
    if lo > hi:
        mask = (tmy.index.month >= lo) | (tmy.index.month <= hi)
    else:
        mask = (tmy.index.month >= lo) & (tmy.index.month <= hi)

    winter = tmy.loc[mask, "temp_air"]
    daily_mean = winter.resample("D").mean()
    coldest_date = daily_mean.idxmin()
    print(f"  Coldest day: {coldest_date.date()}  "
          f"(daily mean {daily_mean.min():.1f} °C)")

    start_ts = pd.Timestamp(coldest_date.date(), tz=tmy.index.tz)
    # Add an extra day of buffer from the database just in case to safely interpolate
    end_ts_buffer = start_ts + pd.Timedelta(hours=duration_hours + 24)
    
    day_data = tmy.loc[start_ts : end_ts_buffer, ["temp_air"]]

    # Resample / interpolate to 1-minute resolution
    day_1min = day_data.resample("1min").interpolate("linear")
    
    # Ensure exact number of minutes
    idx = pd.date_range(start_ts, periods=duration_hours * 60, freq="1min")
    day_1min = day_1min.reindex(idx).interpolate("linear").ffill().bfill()
    return day_1min


def select_peak_load_day(
    tmy: pd.DataFrame,
    month_range: tuple[int, int] = (11, 3),
    duration_hours: int = 24,
    occupied_hours: tuple[int, int] = (6, 22),
) -> pd.DataFrame:
    """
    Return a DataFrame (1-minute resolution) anchored to the winter day with
    the highest expected unmanaged building demand (no EVs).

    Uses occupied-hour heating degree-hours (HDH) below the residential balance
    point of 18 °C as a demand proxy (ASHRAE 90.1). This is more physically
    accurate than selecting on absolute minimum temperature alone:

        demand_proxy(d) = mean_{h in occupied_hours} max(0, 18 - T_h)

    The day maximising this proxy is the most stressful for the unmanaged grid
    without EVs, and is used as the study anchor.

    Parameters
    ----------
    month_range    : (start_month, end_month) inclusive. Wraps across year-end.
    duration_hours : hours to extract starting at midnight of the peak day.
    occupied_hours : (h_start, h_end) occupancy window for HDH weighting.
    """
    lo, hi = month_range
    if lo > hi:
        mask = (tmy.index.month >= lo) | (tmy.index.month <= hi)
    else:
        mask = (tmy.index.month >= lo) & (tmy.index.month <= hi)

    winter = tmy.loc[mask, "temp_air"].copy()

    h_start, h_end = occupied_hours
    occ_mask = (winter.index.hour >= h_start) & (winter.index.hour < h_end)

    BALANCE_POINT_C = 18.0
    hdh = (BALANCE_POINT_C - winter).clip(lower=0.0)
    hdh_occupied = hdh.loc[occ_mask]

    daily_hdh = hdh_occupied.resample("D").mean()
    peak_date = daily_hdh.idxmax()

    print(
        f"  Peak-demand day (no-EV proxy): {peak_date.date()}  "
        f"(occupied HDH = {daily_hdh.max():.2f} °C, "
        f"mean T = {winter.resample('D').mean()[peak_date]:.1f} °C)"
    )
    start_ts = pd.Timestamp(peak_date.date(), tz=tmy.index.tz)
    end_ts_buffer = start_ts + pd.Timedelta(hours=duration_hours + 24)

    day_data = tmy.loc[start_ts:end_ts_buffer, ["temp_air"]]
    day_1min = day_data.resample("1min").interpolate("linear")

    idx = pd.date_range(start_ts, periods=duration_hours * 60, freq="1min")
    day_1min = day_1min.reindex(idx).interpolate("linear").ffill().bfill()
    return day_1min


if __name__ == "__main__":
    tmy = download_tmy()
    print("\n--- Coldest day (temperature minimum) ---")
    cold = select_cold_day(tmy, duration_hours=40)
    print(cold.describe())
    print("\n--- Peak demand day (no-EV HDH proxy) ---")
    peak = select_peak_load_day(tmy, duration_hours=40)
    print(peak.describe())
