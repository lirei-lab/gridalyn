"""Deterministic annual-profile numeric kernel for ev_hosting_flex.

Implements GAP-3 (the SDK has no annual one-call 8760h harness): a pure-numpy,
float64, seed-free parametric base building-load envelope + a deterministic
evening-window EV charging unit profile + a largest-remainder per-bus EV
allocation, all reproducible to 1e-6 (PROF-01/02/03, D-01/D-04/D-05/D-06/D-12).

Design (CONTEXT.md decisions, supersedes the ROADMAP-#1 weather path):

* ``base_load_8760`` (D-01/D-02): an analytic deterministic envelope
  ``nameplate_kw x winter(year) x daily(hour-of-day) x weekly(weekday)`` — winter
  evening-peaked, no weather input, NO RNG. Addressable per bus so the
  downstream-sum proxy can aggregate it.
* ``ev_unit_profile`` (D-04/D-05): a fixed daily evening-window shape tiled across
  365 days, scaled by ``EV_UNIT_KW * DIVERSITY_FACTOR``, flat/seasonless.
* ``allocate_ev_per_bus`` (D-06): distributes a total feeder EV count across buses
  proportional to building count via the largest-remainder method over SORTED bus
  order — deterministic, no RNG, no set/dict iteration; sums exactly to total.

GUARD-02: NO module-scope ``import pandapower`` / ``geopandas`` /
``lightsim2grid``. ``numpy`` is the numeric core. ``np.random.default_rng(SEED)``
is available but the base/EV/allocation paths are RNG-free (largest-remainder
removes the only would-be stochastic step); ``np.random.seed`` is never called.
"""

from __future__ import annotations

import numpy as np

from projects.ev_hosting_flex.scripts.config import (
    CALENDAR_HOURS,
    CALENDAR_START_WEEKDAY,
    CHARGING_WINDOW,
    DAILY_PATTERN,
    DIVERSITY_FACTOR,
    DTYPE,
    EV_UNIT_KW,
    SEED,
    SUMMER_TROUGH_FACTOR,
    WEEKLY_PATTERN,
    WINTER_PEAK_FACTOR,
)

# RNG kept available per the reproducibility contract but UNUSED in every numeric
# path below (largest-remainder allocation is deterministic). Never np.random.seed.
_RNG = np.random.default_rng(SEED)

_DAYS_PER_YEAR = 24  # hours per day; CALENDAR_HOURS / 24 == 365 (non-leap).
_DAILY = np.asarray(DAILY_PATTERN, dtype=DTYPE)
_WEEKLY = np.asarray(WEEKLY_PATTERN, dtype=DTYPE)


def winter_factor(hour_of_year: np.ndarray) -> np.ndarray:
    """Return the float64 seasonal multiplier per hour, winter-peaked.

    A deterministic cosine over the year interpolating between
    ``SUMMER_TROUGH_FACTOR`` (mid-year, ~July) and ``WINTER_PEAK_FACTOR``
    (year ends, Jan/Dec). Because the seasonal term depends only on day-of-year,
    winter exceeds summer at every hour-of-day (D-03).

    Args:
        hour_of_year: Integer hour-of-year array (0 .. CALENDAR_HOURS-1).

    Returns:
        A float64 array of seasonal multipliers aligned to ``hour_of_year``.
    """
    day_of_year = np.asarray(hour_of_year, dtype=DTYPE) // _DAYS_PER_YEAR
    n_days = CALENDAR_HOURS // _DAYS_PER_YEAR
    # cos peaks (=1) at day 0 and day n_days, troughs (=-1) at mid-year.
    season = np.cos(2.0 * np.pi * day_of_year / float(n_days))
    midpoint = (WINTER_PEAK_FACTOR + SUMMER_TROUGH_FACTOR) / 2.0
    amplitude = (WINTER_PEAK_FACTOR - SUMMER_TROUGH_FACTOR) / 2.0
    return (midpoint + amplitude * season).astype(DTYPE)


def daily_factor(hour_of_year: np.ndarray) -> np.ndarray:
    """Return the float64 daily-shape coefficient per hour.

    Indexes ``DAILY_PATTERN`` by ``hour_of_year % 24`` (D-03).

    Args:
        hour_of_year: Integer hour-of-year array.

    Returns:
        A float64 array of daily-shape coefficients aligned to ``hour_of_year``.
    """
    hod = np.asarray(hour_of_year) % 24
    return _DAILY[hod]


def weekly_factor(hour_of_year: np.ndarray) -> np.ndarray:
    """Return the float64 weekly-shape coefficient per hour.

    Weekday = ``((hour_of_year // 24) + CALENDAR_START_WEEKDAY) % 7`` (Mon=0),
    indexing ``WEEKLY_PATTERN`` (D-03).

    Args:
        hour_of_year: Integer hour-of-year array.

    Returns:
        A float64 array of weekly-shape coefficients aligned to ``hour_of_year``.
    """
    weekday = ((np.asarray(hour_of_year) // 24) + CALENDAR_START_WEEKDAY) % 7
    return _WEEKLY[weekday]


def base_load_8760(nameplate_kw: np.ndarray) -> np.ndarray:
    """Return the deterministic per-bus annual base building load in kW.

    ``(n_bus, CALENDAR_HOURS)`` float64 =
    ``nameplate_kw[:, None] * winter(hours) * daily(hours) * weekly(hours)``.
    Winter-evening-peaked, no RNG, bit-identical across reruns (D-01/D-02/D-12).

    Args:
        nameplate_kw: Per-bus nameplate kW, SORTED-bus order, shape ``(n_bus,)``.

    Returns:
        A ``(n_bus, CALENDAR_HOURS)`` float64 per-bus hourly base-load array.
    """
    hours = np.arange(CALENDAR_HOURS)
    shape = (winter_factor(hours) * daily_factor(hours) * weekly_factor(hours)).astype(
        DTYPE
    )
    nameplate = np.asarray(nameplate_kw, dtype=DTYPE)
    return nameplate[:, None] * shape[None, :]


def ev_unit_profile() -> np.ndarray:
    """Return the deterministic per-EV evening-window annual unit draw in kW.

    A fixed 24h window shape (flat inside ``CHARGING_WINDOW``, zero outside) tiled
    across 365 days and scaled by ``EV_UNIT_KW * DIVERSITY_FACTOR``. Flat/
    seasonless across days (D-04/D-05); deterministic, no RNG.

    Returns:
        A ``(CALENDAR_HOURS,)`` float64 per-EV unit-draw array.
    """
    start, end = CHARGING_WINDOW
    day_shape = np.zeros(24, dtype=DTYPE)
    day_shape[start:end] = float(EV_UNIT_KW) * float(DIVERSITY_FACTOR)
    n_days = CALENDAR_HOURS // 24
    return np.tile(day_shape, n_days).astype(DTYPE)


def allocate_ev_per_bus(total_ev: int, building_count: np.ndarray) -> np.ndarray:
    """Distribute ``total_ev`` across buses proportional to building count.

    Largest-remainder (Hamilton) method over SORTED-bus order: floor the
    proportional shares, then assign the leftover one EV at a time to the buses
    with the largest fractional parts, breaking ties by ASCENDING bus position.
    Deterministic, no RNG, no set/dict iteration; the result sums exactly to
    ``total_ev`` (integer conservation, D-06).

    Args:
        total_ev: Total feeder EV count to distribute (>= 0).
        building_count: Per-bus building/load count in SORTED-bus order,
            shape ``(n_bus,)``, with a positive total.

    Returns:
        An integer ``(n_bus,)`` array summing exactly to ``total_ev``.
    """
    counts = np.asarray(building_count, dtype=DTYPE)
    n_bus = counts.shape[0]
    if total_ev <= 0:
        return np.zeros(n_bus, dtype=np.int64)
    total_buildings = counts.sum()
    if total_buildings <= 0.0:
        raise ValueError(
            "allocate_ev_per_bus received an all-zero building_count "
            f"(sum={total_buildings}); cannot distribute {total_ev} EVs "
            "proportionally. Remediation: pass the per-bus load/building counts "
            "from node_building_count.json for the selected feeder's buses."
        )
    raw = counts / total_buildings * float(total_ev)
    floor = np.floor(raw).astype(np.int64)
    remainder = int(total_ev) - int(floor.sum())
    if remainder > 0:
        frac = raw - floor
        # Largest fractional part first; ascending bus index as the tie-break.
        order = np.lexsort((np.arange(n_bus), -frac))
        floor[order[:remainder]] += 1
    return floor
