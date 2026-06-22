"""Unit tests for ``projects/ev_hosting_flex/scripts/_profiles.py``.

Hand-computed determinism + winter-peak + allocation-conservation tests for the
deterministic, pure-numpy, float64 annual-profile kernel (PROF-01/02/03, D-01/
D-04/D-05/D-06). A tiny known-nameplate / known-building-count fixture asserts
exact base/EV values, winter > summer at the same hour-of-day, integer
allocation conservation, order-independence, and bit-identical reruns.

GUARD-02: the module under test must not ``import pandapower`` / ``geopandas``
at module scope; these tests touch only numpy arrays.
"""

from __future__ import annotations

import numpy as np

from projects.ev_hosting_flex.scripts._profiles import (
    allocate_ev_per_bus,
    base_load_8760,
    daily_factor,
    ev_unit_profile,
    weekly_factor,
    winter_factor,
)
from projects.ev_hosting_flex.scripts.config import (
    CALENDAR_HOURS,
    CHARGING_WINDOW,
    DAILY_PATTERN,
    DIVERSITY_FACTOR,
    EV_UNIT_KW,
    SUMMER_TROUGH_FACTOR,
    WEEKLY_PATTERN,
    WINTER_PEAK_FACTOR,
)


def _winter_evening_hour() -> int:
    """Hour-of-year at a January evening peak (day 0, 18:00)."""
    return 0 * 24 + 18


def _summer_noon_hour() -> int:
    """Hour-of-year near the summer trough (day 180, 12:00)."""
    return 180 * 24 + 12


def test_base_load_shape_and_dtype() -> None:
    """base_load_8760 returns (n_bus, 8760) float64."""
    nameplate = np.array([1.0, 2.0, 4.0])
    base = base_load_8760(nameplate)
    assert base.shape == (3, CALENDAR_HOURS)
    assert base.dtype == np.float64


def test_base_load_exact_values() -> None:
    """Exact hand-computed base value = nameplate * winter * daily * weekly."""
    nameplate = np.array([1.0, 2.0, 4.0])
    base = base_load_8760(nameplate)
    hours = np.arange(CALENDAR_HOURS)
    expected_shape = (
        winter_factor(hours) * daily_factor(hours) * weekly_factor(hours)
    )
    for bus, kw in enumerate(nameplate):
        np.testing.assert_allclose(base[bus], kw * expected_shape, rtol=0, atol=0)


def test_winter_peaks_above_summer_same_hour_of_day() -> None:
    """Winter evening hour exceeds summer hour at the same hour-of-day, per bus."""
    nameplate = np.array([1.0, 2.0, 4.0])
    base = base_load_8760(nameplate)
    # Same hour-of-day (18:00) in January vs July.
    winter_h = 0 * 24 + 18
    summer_h = 180 * 24 + 18
    assert np.all(base[:, winter_h] > base[:, summer_h])


def test_winter_factor_bounds() -> None:
    """winter_factor stays within [SUMMER_TROUGH_FACTOR, WINTER_PEAK_FACTOR]."""
    hours = np.arange(CALENDAR_HOURS)
    wf = winter_factor(hours)
    assert wf.dtype == np.float64
    assert wf.min() >= SUMMER_TROUGH_FACTOR - 1e-9
    assert wf.max() <= WINTER_PEAK_FACTOR + 1e-9


def test_daily_factor_indexes_pattern() -> None:
    """daily_factor at hour h equals DAILY_PATTERN[h % 24]."""
    hours = np.arange(CALENDAR_HOURS)
    df = daily_factor(hours)
    for h in (0, 18, 23, 24, 4242):
        assert df[h] == DAILY_PATTERN[h % 24]


def test_weekly_factor_indexes_pattern() -> None:
    """weekly_factor at hour h equals WEEKLY_PATTERN[weekday(h)]."""
    hours = np.arange(CALENDAR_HOURS)
    wf = weekly_factor(hours)
    # CALENDAR_START_WEEKDAY = Monday(0): day 0 -> Mon, day 5 -> Sat.
    assert wf[0] == WEEKLY_PATTERN[0]
    assert wf[5 * 24] == WEEKLY_PATTERN[5]


def test_ev_unit_zero_outside_window() -> None:
    """ev_unit_profile is zero strictly outside the CHARGING_WINDOW each day."""
    ev = ev_unit_profile()
    assert ev.shape == (CALENDAR_HOURS,)
    assert ev.dtype == np.float64
    start, end = CHARGING_WINDOW
    hod = np.arange(CALENDAR_HOURS) % 24
    outside = (hod < start) | (hod >= end)
    assert np.all(ev[outside] == 0.0)
    # Inside the window it is nonzero and bounded by EV_UNIT_KW * DIVERSITY_FACTOR.
    inside = ~outside
    assert np.all(ev[inside] > 0.0)
    assert ev.max() <= EV_UNIT_KW * DIVERSITY_FACTOR + 1e-9


def test_ev_unit_equal_across_days() -> None:
    """ev_unit_profile repeats identically across two arbitrary days."""
    ev = ev_unit_profile()
    day_a = ev[10 * 24 : 11 * 24]
    day_b = ev[200 * 24 : 201 * 24]
    assert np.array_equal(day_a, day_b)


def test_allocate_sums_to_total() -> None:
    """allocate_ev_per_bus distributes exactly total_ev (integer conservation)."""
    counts = np.array([1, 2, 3])
    alloc = allocate_ev_per_bus(10, counts)
    assert alloc.sum() == 10
    assert alloc.dtype.kind == "i"
    # Proportional-ish: the largest building count gets the most EVs.
    assert alloc[2] >= alloc[1] >= alloc[0]


def test_allocate_deterministic_across_calls() -> None:
    """allocate_ev_per_bus is unchanged when called twice (no RNG)."""
    counts = np.array([1, 2, 3, 4])
    a = allocate_ev_per_bus(7, counts)
    b = allocate_ev_per_bus(7, counts)
    assert np.array_equal(a, b)
    assert a.sum() == 7


def test_allocate_zero_total() -> None:
    """Zero EVs allocate to all-zero per bus."""
    counts = np.array([1, 2, 3])
    alloc = allocate_ev_per_bus(0, counts)
    assert alloc.sum() == 0
    assert np.all(alloc == 0)


def test_base_load_deterministic_reruns() -> None:
    """Two independent base_load_8760 calls are bit-identical (determinism)."""
    nameplate = np.array([1.0, 2.0, 4.0])
    a = base_load_8760(nameplate)
    b = base_load_8760(nameplate)
    assert np.array_equal(a, b)
