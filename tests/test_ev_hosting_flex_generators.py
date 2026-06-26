"""Unit tests for ``projects/ev_hosting_flex/scripts/_generators.py`` (Phase 13).

The success anchor for the design-day Monte-Carlo generation seam (GEN-01..04).
These tests pin the EMPIRICALLY-LOCKED operating point (``R = 7.0``,
``p_heat_max = 13.0``, design day ``1990-01-19``, EV-free base ~82–87% of the
71.25 kW rating / ~8.4 kW/home, firm region) — they are written to the empirical
values, NOT to whatever the code happens to emit. They lock:

* the design-day selection (1990-01-19),
* the locked building base %rating + per-home coincident peak at R=7.0/p_heat=13.0,
* the MDPI nested-EV pool monotonicity (GEN-03) and pinned draw order (a recorded
  sha256 golden — any RNG-order drift trips CI),
* the ``Q_real`` byte-stability across two same-seed runs (GEN-01 / SEAL-01),
* ``Q_design`` tracking ``Q_real``'s predictable mean (GEN-04, corr ≥ 0.9),
* the no-silent-SDK-fallback guard (GEN-01 / T-13-03).

GUARD-02: the module under test must NOT ``import pandapower`` / ``geopandas`` /
``lightsim2grid`` at module scope; these tests touch only numpy/pandas arrays + the
committed TMY CSV and the SDK numeric building agent (numpy/pandas/pvlib — pvlib is
a base dep). They are cache-free (the gitignored topology cache lives only in the
main tree; the home count is passed via ``config.N_HOMES_FALLBACK``).
"""

from __future__ import annotations

import hashlib
import sys

import numpy as np
import pytest

from projects.ev_hosting_flex.scripts import _generators as _generators_mod
from projects.ev_hosting_flex.scripts._generators import (
    ev_nested_pool,
    make_design_day_ensemble,
    make_q_design,
    select_design_day,
)
from projects.ev_hosting_flex.scripts.config import (
    DESIGN_DAY_RES_MINUTES,
    N_HOMES_FALLBACK,
    POWER_FACTOR,
    SEED,
    TRANSFORMER_KVA,
)

# Modest K so the SDK-building test stays well under 60 s (each realization runs a
# 6-h burn-in + 24-h 1-min RC simulation of 7 dwellings). K=12 is enough for a
# stable p50 base-peak at the locked operating point (the firm region was verified
# at K=60; the p50/p90 %rating is stable in [80,90]% by K~12).
_TEST_K = 12

_RATING_KW = TRANSFORMER_KVA * POWER_FACTOR  # 71.25 kW usable

# Recorded golden digest of the fixed-seed nested-EV pool (seed=42, n_ev_max=6,
# hourly). Any change to the pinned MDPI per-EV draw order (random -> choice ->
# lognormal -> normal) or the nested cumsum trips this literal (the byte-stability
# tripwire, GEN-03 / SEAL-01). Recompute deliberately (and document the
# re-baseline) only if the draw order is ever intentionally changed.
_GOLDEN_EV_POOL_SHA256 = (
    "420b92a19418409907ab5b024e2cf0dc7099bc8ca9cb11bece29eb59219de229"
)


def _content_sha256(arr: np.ndarray) -> str:
    """Canonical-bytes sha256 with signed-zero kill (mirrors the pipeline)."""
    canonical = np.ascontiguousarray(arr, dtype="float64") + 0.0
    return hashlib.sha256(canonical.tobytes()).hexdigest()


# ───────────────────────── design-day selection ──────────────────────────


def test_design_day_is_1990_01_19() -> None:
    """``select_design_day`` selects the locked 1990-01-19 design day, 1-min frame."""
    day = select_design_day()
    assert str(day.index[0].date()) == "1990-01-19"
    # native 1-min resolution over the 24-h day, non-empty, temp present.
    assert len(day) == 24 * 60
    assert "temp_air" in day.columns
    assert day["temp_air"].notna().all()


# ───────────────────── building base at the locked rating ─────────────────


def test_building_base_lands_at_locked_rating() -> None:
    """EV-free building base p50 peak in [80,90]% rating, per-home in [7.5,10] kW.

    The locked GEN-02 operating point (R=7.0/p_heat_max=13.0 on the 7-home idx-62
    unit, the firm-region anchor from exp_firmsweep). K=_TEST_K (documented above).
    """
    res = make_design_day_ensemble(
        n_homes=N_HOMES_FALLBACK, k=_TEST_K, res_minutes=DESIGN_DAY_RES_MINUTES
    )
    q_real = res["Q_real"]
    assert q_real.shape == (_TEST_K, 24)
    base_peak = q_real.max(axis=1)  # (K,) per-realization feeder base peak (kW)
    p50_pct = float(np.percentile(base_peak, 50)) / _RATING_KW * 100.0
    assert 80.0 <= p50_pct <= 90.0, f"base p50={p50_pct:.1f}% rating (want [80,90])"
    per_home_p50 = float(np.percentile(base_peak, 50)) / N_HOMES_FALLBACK
    assert (
        7.5 <= per_home_p50 <= 10.0
    ), f"per-home coincident peak={per_home_p50:.2f} kW/home (want [7.5,10])"


# ───────────────────────── MDPI nested-EV pool ───────────────────────────


def test_ev_pool_monotonic_in_count() -> None:
    """``ev_nested_pool`` rows are non-decreasing per step; row 0 is all-zero (GEN-03)."""
    pool = ev_nested_pool(np.random.default_rng(SEED), 12, DESIGN_DAY_RES_MINUTES)
    assert pool.shape == (13, 24)
    assert np.all(pool[0] == 0.0), "row 0 (zero EVs) must be all-zero"
    # adding an EV never removes load at any step (monotonic non-decreasing).
    assert np.all(np.diff(pool, axis=0) >= -1e-9)


def test_ev_draw_order_pinned() -> None:
    """Two same-seed pools are byte-identical AND match the recorded MDPI golden."""
    a = ev_nested_pool(np.random.default_rng(42), 6, 60)
    b = ev_nested_pool(np.random.default_rng(42), 6, 60)
    assert np.array_equal(a, b)
    assert a.dtype == np.float64
    assert _content_sha256(a) == _GOLDEN_EV_POOL_SHA256


# ───────────────────────── Q_real / determinism ──────────────────────────


def test_q_real_byte_stable() -> None:
    """Two ``make_design_day_ensemble`` calls with the same seed give equal Q_real."""
    r1 = make_design_day_ensemble(
        n_homes=N_HOMES_FALLBACK, k=_TEST_K, res_minutes=DESIGN_DAY_RES_MINUTES
    )
    r2 = make_design_day_ensemble(
        n_homes=N_HOMES_FALLBACK, k=_TEST_K, res_minutes=DESIGN_DAY_RES_MINUTES
    )
    assert r1["Q_real"].dtype == np.float64
    assert r1["Q_real"].shape == (_TEST_K, 24)
    assert np.array_equal(r1["Q_real"], r2["Q_real"])  # byte-stable (GEN-01)
    assert np.array_equal(r1["Q_design"], r2["Q_design"])
    assert np.array_equal(r1["ev_pool"], r2["ev_pool"])


def test_no_global_numpy_random_usage() -> None:
    """The kernel never seeds / draws from the global ``np.random`` (determinism)."""
    import inspect

    src = inspect.getsource(_generators_mod)
    # the global state-mutating / global-draw APIs must not appear in the kernel.
    assert "np.random.seed" not in src
    assert "np.random.rand(" not in src
    assert "np.random.normal(" not in src
    # every Generator is built explicitly via default_rng.
    assert "np.random.default_rng" in src


# ─────────────────────── Q_design tracks Q_real mean ─────────────────────


def test_q_design_tracks_q_real_predictable_mean() -> None:
    """``make_q_design`` correlates >= 0.9 with the per-step mean of Q_real (GEN-04).

    Q_design is a smoothing/forecast of Q_real's predictable part — never an
    independent model — so its max deviation from that mean stays within a
    documented tolerance (here < 15% of the mean's peak, comfortably tight).
    """
    res = make_design_day_ensemble(
        n_homes=N_HOMES_FALLBACK, k=_TEST_K, res_minutes=DESIGN_DAY_RES_MINUTES
    )
    q_real = res["Q_real"]
    q_design = res["Q_design"]
    mean_shape = q_real.mean(axis=0)
    corr = float(np.corrcoef(q_design, mean_shape)[0, 1])
    assert corr >= 0.9, f"Q_design corr with Q_real mean = {corr:.4f} (want >= 0.9)"
    max_dev_frac = float(np.abs(q_design - mean_shape).max()) / float(mean_shape.max())
    assert max_dev_frac < 0.15, (
        f"Q_design max deviation = {max_dev_frac:.3f} of the mean peak "
        "(want < 0.15 — it is a smoothing/forecast, not an independent model)"
    )


def test_q_design_is_deterministic_given_seed() -> None:
    """``make_q_design`` is byte-stable for a fixed ensemble + seeded Generator."""
    q_real = np.tile(np.linspace(40.0, 60.0, 24), (8, 1)).astype("float64")
    d1 = make_q_design(q_real, np.random.default_rng(SEED + 1))
    d2 = make_q_design(q_real, np.random.default_rng(SEED + 1))
    assert d1.dtype == np.float64
    assert d1.shape == (24,)
    assert np.array_equal(d1, d2)


# ───────────────────── no silent SDK fallback (GEN-01) ────────────────────


def test_no_silent_sdk_fallback_in_source() -> None:
    """The governed path imports the SDK agents and RAISES on ImportError (no fallback)."""
    import inspect

    src = inspect.getsource(_generators_mod)
    # the SDK symbols are wired in the governed path (not a hand-rolled base).
    assert "make_buildings" in src
    assert "simulate_buildings" in src
    assert "select_peak_load_day" in src
    # each deferred import is guarded with a raised ImportError (no silent
    # substitution of a hand-rolled base).
    assert "raise ImportError" in src
    assert "no silent fallback" in src


def test_select_design_day_raises_when_sdk_unavailable(monkeypatch) -> None:
    """Breaking the SDK weather import makes ``select_design_day`` RAISE, not fall back."""
    import builtins

    real_import = builtins.__import__

    def _broken_import(name, *args, **kwargs):
        if name == "gridalyn.assets.datagen.data.weather":
            raise ImportError("simulated missing SDK weather module")
        return real_import(name, *args, **kwargs)

    # drop any cached module so the deferred import re-runs through the breaker.
    monkeypatch.delitem(
        sys.modules, "gridalyn.assets.datagen.data.weather", raising=False
    )
    monkeypatch.setattr(builtins, "__import__", _broken_import)
    with pytest.raises(ImportError, match="hand-rolled"):
        select_design_day()
