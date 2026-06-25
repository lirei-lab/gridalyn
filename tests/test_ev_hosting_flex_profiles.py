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
    expected_shape = winter_factor(hours) * daily_factor(hours) * weekly_factor(hours)
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


# ─── Stage-3 TMY + stochastic re-baseline path (RECAL-03/04/11, D-08/D-13) ────
# The deterministic kernel above is DEPRECATED (D-14) but kept importable/diffable;
# these tests cover the NEW stage path that supersedes it: the TMY heating-degree
# base + the seeded byte-stable K stochastic-EV stack.

import shutil  # noqa: E402
from pathlib import Path  # noqa: E402

from projects.ev_hosting_flex.scripts._stochastic import (  # noqa: E402
    ev_realizations,
    tmy_base,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    ADMD_KW,
    PROJECT_CACHE_DIR,
    SEED,
    K,
)
from projects.ev_hosting_flex.scripts.pipeline.generate_annual_profiles import (  # noqa: E402
    derive_annual_profiles,
)

_REQUIRED_CACHE = [
    "node_nameplate_kw.json",
    "node_building_count.json",
    "downstream_bus_map.json",
    "feeder_selection.json",
]


def _cache_ready() -> bool:
    """True iff the stage-2 cache sidecars are present in the project outputs."""
    return all((PROJECT_CACHE_DIR / name).is_file() for name in _REQUIRED_CACHE)


def test_tmy_base_addressable_per_bus_and_dtype() -> None:
    """tmy_base returns (n_bus, 8760) float64, per-bus = home-share * per_home."""
    share = np.array([1.0, 2.0, 4.0], dtype=np.float64)
    base = tmy_base(share)
    assert base.shape == (3, CALENDAR_HOURS)
    assert base.dtype == np.float64
    # Per-bus base scales linearly with the home share (D-02/D-08 addressable).
    np.testing.assert_allclose(base[1], 2.0 * base[0], rtol=0, atol=1e-12)
    np.testing.assert_allclose(base[2], 4.0 * base[0], rtol=0, atol=1e-12)


def test_tmy_base_per_home_peak_near_admd() -> None:
    """The single-home TMY base peaks in the CLPU-lifted [7.5, 9.5] kW band.

    Re-based under cold-load pickup (260625-pwz): the steady design-cold heating
    envelope is anchored to ADMD (~6.5 kW), but the coldest EVENING recovery hour is
    multiplied by ``clpu_factor`` (up to CLPU_PEAK=1.40), lifting the annual per-home
    peak to ~8.3 kW. The pre-CLPU band was ``ADMD_KW ± 1.5``; the CLPU port
    deliberately lifts the cold-evening peak (the congestion-driving tail). The ADMD
    anchor remains the off-peak / non-evening cold floor.
    """
    share = np.array([1.0], dtype=np.float64)
    base = tmy_base(share)
    peak = float(base.max())
    # CLPU-lifted design-cold per-home peak band; ADMD (~6.5 kW) is the steady floor.
    assert 7.5 <= peak <= 9.5, f"CLPU per-home peak {peak} outside [7.5, 9.5]"
    assert peak >= ADMD_KW


def test_ev_realizations_byte_stable_under_fixed_seed() -> None:
    """Two ev_realizations calls under the same SEED are byte-identical (D-13)."""
    a = ev_realizations(np.random.default_rng(SEED), 8, n_ev=2, n_bus=1)
    b = ev_realizations(np.random.default_rng(SEED), 8, n_ev=2, n_bus=1)
    assert np.array_equal(a, b)


def _seed_tmp_cache(tmp: Path) -> Path:
    """Copy the required stage-2 cache sidecars into a tmp cache dir."""
    dst = tmp / "cache"
    dst.mkdir(parents=True, exist_ok=True)
    for name in _REQUIRED_CACHE:
        shutil.copy(PROJECT_CACHE_DIR / name, dst / name)
    return dst


import pytest  # noqa: E402


@pytest.mark.skipif(
    not _cache_ready(),
    reason=(
        "ev_hosting_flex stage-2 cache not present; run "
        "prepare_topology_cache.py first"
    ),
)
def test_derive_annual_profiles_tmy_stochastic(tmp_path: Path) -> None:
    """End-to-end stage 3: TMY base + seeded K EV stack + re-baseline note.

    Asserts the TMY base parquet + the (K, 8760) EV stack .npy are written, the
    summary carries the re-baseline note + the EV-stack sha256, and a second run
    reproduces a byte-identical EV-stack sha256 (D-13).
    """
    cache_dir = _seed_tmp_cache(tmp_path)
    data_dir = tmp_path / "data"

    derived = derive_annual_profiles(cache_dir, data_dir)
    summary = derived["summary"]

    # Artifacts exist.
    assert (data_dir / "base_load_8760.parquet").is_file()
    assert (data_dir / "ev_load_unit.parquet").is_file()
    stack_path = data_dir / "ev_stack_K.npy"
    assert stack_path.is_file()

    # The EV stack is the (K, 8760) seeded realization stack.
    stack = np.load(stack_path)
    assert stack.shape == (int(K), CALENDAR_HOURS)
    assert stack.dtype == np.float64

    # The re-baseline note is carried in the summary.
    assert "TMY" in summary["divergence_note"]
    assert "stochastic" in summary["divergence_note"]
    assert summary["k_realizations"] == int(K)
    assert summary["seed"] == int(SEED)
    assert "ev_stack_content_sha256" in summary

    # Second run reproduces the byte-identical EV-stack sha256 (D-13).
    data_dir2 = tmp_path / "data2"
    derived2 = derive_annual_profiles(cache_dir, data_dir2)
    assert (
        derived2["summary"]["ev_stack_content_sha256"]
        == summary["ev_stack_content_sha256"]
    )
