"""
weather.py – Download TMY data for Trois-Rivières, QC and extract the coldest day.

Uses pvlib.iotools.get_pvgis_tmy() (PVGIS SARAH-3 dataset).
Falls back to a synthetic offline profile if PVGIS is unreachable.

Caching
-------
The first successful download (or synthetic generation) is stored as a pickle
under the generated cache directory and reused on every subsequent call. Set
GRIDALYN_DATAGEN_CACHE_DIR, or the legacy GEOPOWER_DATAGEN_CACHE_DIR, to
override the default cache location. Pass force_refresh=True to bypass the cache
and re-fetch from PVGIS.
"""

from __future__ import annotations

import os
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
import pvlib

# Trois-Rivières, QC  (WMO 717200)
LAT = 46.35
LON = -72.55
ALT = 5  # metres ASL

PVGIS_MONTHS = list(range(1, 13))  # full year

REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_CACHE_DIR = REPO_ROOT / "examples" / "generated" / "cache"
_CACHE_DIR = Path(
    os.environ.get(
        "GRIDALYN_DATAGEN_CACHE_DIR",
        os.environ.get("GEOPOWER_DATAGEN_CACHE_DIR", _DEFAULT_CACHE_DIR),
    )
)
_CACHE_FILE = _CACHE_DIR / "tmy_trois_rivieres.pkl"


def download_tmy(force_refresh: bool = False) -> pd.DataFrame:
    """
    Return an 8760-row DataFrame with columns including 'temp_air' (°C)
    and a DatetimeIndex in local standard time (UTC-5).

    The result is cached on disk after the first call. Subsequent calls
    load from cache instantly without hitting the network.

    Parameters
    ----------
    force_refresh : if True, ignore any existing cache and re-download.
    """
    if not force_refresh and _CACHE_FILE.exists():
        print(f"  Loading TMY from cache ({_CACHE_FILE.name}) …")
        with open(_CACHE_FILE, "rb") as f:
            return pickle.load(f)

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
        print(f"  TMY fetched: {len(tmy)} rows, index tz={tmy.index.tz}")
    except Exception as exc:
        print(f"  PVGIS unavailable ({exc}), generating synthetic winter profile …")
        tmy = _synthetic_winter_tmy()

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(_CACHE_FILE, "wb") as f:
        pickle.dump(tmy, f)
    print(f"  TMY cached to {_CACHE_FILE.name}")
    return tmy


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
    monthly_std = {m: 3.0 for m in range(1, 13)}

    rng = pd.date_range("2023-01-01", periods=8760, freq="h",
                        tz="America/Toronto")
    temps = []
    rng_gen = np.random.default_rng(42)
    for ts in rng:
        base = monthly_mean[ts.month]
        sigma = monthly_std[ts.month]
        # Diurnal variation: −3 °C at 06:00 UTC-5, +3 °C at 14:00
        diurnal = -3 * np.cos(2 * np.pi * (ts.hour - 14) / 24)
        # Add extreme cold snaps (Jan-Feb) via skewed noise to hit -30C occasionally
        if base < -5 and rng_gen.random() < 0.15:
            skewed_noise = rng_gen.normal(-4.0, 3.5) 
        else:
            skewed_noise = rng_gen.normal(0, 1.0)
        temps.append(base + diurnal + skewed_noise * sigma * 0.8)

    df = pd.DataFrame({"temp_air": temps}, index=rng)
    df["ghi"] = 0.0  # not needed for thermal simulation
    return df


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
    hdh_occupied = hdh.where(occ_mask, other=0.0)

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
