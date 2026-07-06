"""Unit tests for ``projects/ev_hosting_flex/scripts/_economics.py`` (ECON-03).

Exercises the non-wires economics + energy-preserving deferral hosting kernel
(ECON-01, D-16-1..D-16-5) against hand-built fixtures with KNOWN math: the single
``flex_cost`` ledger identity (no double-count), break-even monotonicity in a ``c_r``
sweep, deferral-NPV sign/magnitude sanity, energy-preserving deferral, the pinned-seed
``content_sha256`` byte-stability of the deferral count, and the located ValueErrors.

These reconciliation tests are NON-vacuous: the deferral model yields non-zero Σ (the
Phase-15 two-stage controller gave Σ=0), so the ledger / monotonicity / NPV assertions
all exercise real quantities.

GUARD-02: the kernel is numpy-only at module scope; this test never ``import
pandapower``.
"""

from __future__ import annotations

import numpy as np
import pytest

from projects.ev_hosting_flex.scripts._economics import (
    breakeven_sweep,
    crf,
    deferral_hosting_count,
    deferral_npv,
    flex_cost,
    reinforcement_annual,
    undeliverable_energy,
)
from projects.ev_hosting_flex.scripts.config import (
    C_A,
    C_R_BASE,
    CAPEX_UPGRADE,
    DEFERRAL_ENROLLMENT_FRACTION,
    DESIGN_DAY_RES_MINUTES,
    DISCOUNT_RATE,
    FIRM_PCONG_TOLERANCE,
    LIFE_YEARS,
    POWER_FACTOR,
    PROJECT_OUTPUTS_DIR,
    TOL_FRACTION,
    TRANSFORMER_KVA,
)

# ─── Governed seed-42 design-day ensemble (gitignored cache; skipif in CI) ───
# The deferral headline is pinned against the SAME on-disk q_real.npy /
# ev_pool_design.npy the firm count is pinned against (test_ev_hosting_flex_congestion
# ::test_governed_ensemble_firm_three). The cache is gitignored (MEMORY: regenerate in
# the MAIN tree; skipif-skips in CI) — reuse the sibling cache-ready skip pattern.
_PROJECT_DATA_DIR = PROJECT_OUTPUTS_DIR / "data"
_RATING_KW = float(TRANSFORMER_KVA) * float(POWER_FACTOR)  # 71.25 (pf pinned)
_REQUIRED_NPY = ["q_real.npy", "ev_pool_design.npy"]


def _project_cache_ready() -> bool:
    """True iff the Phase-13 design-day .npy ensemble is present on disk.

    Mirrors the sibling ``test_ev_hosting_flex_congestion._project_cache_ready`` cache
    guard so the governed regression runs locally on the regenerated cache and skips
    cleanly in CI (the cache is gitignored).
    """
    return all((_PROJECT_DATA_DIR / name).is_file() for name in _REQUIRED_NPY)


def _toy_pool(k: int = 4, ev_max: int = 6, n_steps: int = 24) -> np.ndarray:
    """A tiny nested-cumulative EV pool with a known overnight charging shape.

    Row ``n`` is the cumulative demand of the first ``n`` EVs; each EV adds a flat
    2.0 kW block over the overnight window [20, 24) so the pool is strictly nested
    (monotone non-decreasing along the EV axis), float64.
    """
    pool = np.zeros((k, ev_max + 1, n_steps), dtype="float64")
    for n in range(1, ev_max + 1):
        block = np.zeros(n_steps, dtype="float64")
        block[20:24] = 2.0 * n  # cumulative: n EVs each 2.0 kW overnight
        pool[:, n, :] = block[None, :]
    return pool


def _toy_q_real(k: int = 4, n_steps: int = 24, base: float = 10.0) -> np.ndarray:
    """A tiny (k, n_steps) EV-free building base with an evening peak (kW)."""
    q = np.full((k, n_steps), base, dtype="float64")
    q[:, 17:20] = base + 5.0  # evening human-activity peak
    return q


# ─── ECON-03: the single ledger identity (no double-count) ───────────────────


def test_ledger_no_double_count() -> None:
    """flex_cost(Σr, Σa) == c_r·Σr + c_a·Σa elementwise (the one ledger function)."""
    kw_days = np.array([1.0, 2.5, 4.0], dtype="float64")  # Σr
    activated = np.array([10.0, 25.0, 40.0], dtype="float64")  # Σa
    got = flex_cost(kw_days, activated, C_R_BASE, C_A)
    expect = float(C_R_BASE) * kw_days + float(C_A) * activated
    np.testing.assert_allclose(got, expect, atol=1e-12)
    # Spot-check one element against hand math (no double-count of either term).
    assert float(got[1]) == pytest.approx(float(C_R_BASE) * 2.5 + float(C_A) * 25.0)


# ─── ECON-03: break-even monotonic in a c_r sweep ────────────────────────────


def test_breakeven_monotonic_in_cr() -> None:
    """The break-even penetration p* is non-increasing as c_r rises."""
    pen_grid = [0.4, 1.0, 1.6, 2.2, 2.8, 3.4, 4.0]
    # Monotone-increasing per-penetration quantities so flex cost rises with p.
    kw_days = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0], dtype="float64")
    activated = np.array([5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0], dtype="float64")
    c_r_grid = [0.5, 1.0, 2.0, 4.0, 6.0, 8.0]
    reinf = reinforcement_annual(crf(DISCOUNT_RATE, LIFE_YEARS), CAPEX_UPGRADE)
    rows = breakeven_sweep(pen_grid, kw_days, activated, c_r_grid, C_A, reinf)
    p_star = [row["p_star"] for row in rows]
    diffs = np.diff(np.asarray(p_star, dtype="float64"))
    assert bool(np.all(diffs <= 1e-9)), f"p* not non-increasing in c_r: {p_star}"


# ─── ECON-03: deferral NPV sign/magnitude sanity ─────────────────────────────


def test_deferral_npv_sane() -> None:
    """NPV >= 0 and finite when flex is cheaper than reinforcement; ~0 otherwise."""
    pen_grid = [0.4, 1.0, 2.0, 3.0, 4.0]
    kw_days = np.array([0.5, 1.0, 1.5, 2.0, 2.5], dtype="float64")
    activated = np.array([2.0, 4.0, 6.0, 8.0, 10.0], dtype="float64")
    reinf = reinforcement_annual(crf(DISCOUNT_RATE, LIFE_YEARS), CAPEX_UPGRADE)
    # Beneficial regime: small flex cost (low c_r/c_a) below the annualized reinforce.
    npv_good = deferral_npv(
        15.0,
        pen_grid,
        kw_days,
        activated,
        c_r=C_R_BASE,
        c_a=C_A,
        discount_rate=DISCOUNT_RATE,
        horizon=LIFE_YEARS,
        p_firm=3.0 / 7.0,
        reinf_annual=reinf,
        p_feas=4.0,
    )
    assert np.isfinite(npv_good)
    assert npv_good >= 0.0
    assert npv_good > 0.0  # non-vacuous: deferral is beneficial here
    # Never-beneficial regime: a huge c_r makes flex always pricier than reinforce.
    npv_zero = deferral_npv(
        15.0,
        pen_grid,
        kw_days,
        activated,
        c_r=1.0e9,
        c_a=C_A,
        discount_rate=DISCOUNT_RATE,
        horizon=LIFE_YEARS,
        p_firm=3.0 / 7.0,
        reinf_annual=reinf,
        p_feas=4.0,
    )
    assert npv_zero == pytest.approx(0.0)


# ─── ECON-03: energy-preserving deferral ─────────────────────────────────────


def test_deferral_energy_preserving() -> None:
    """Zero undeliverable when EV energy fits the off-peak envelope; positive if not."""
    pool = _toy_pool()
    res_minutes = 60
    rating = 100.0  # generous rating: overnight headroom absorbs all enrolled energy
    fits = undeliverable_energy(
        _toy_q_real(), pool, 4, rating, res_minutes, enrollment_fraction=0.30
    )
    assert fits == pytest.approx(0.0)
    # Tight rating below the base: the off-peak headroom cannot absorb the EV energy
    # AND the un-enrolled EVs push the residual over rating ⇒ positive undeliverable.
    tight = undeliverable_energy(
        _toy_q_real(base=10.0), pool, 6, 11.0, res_minutes, enrollment_fraction=0.30
    )
    assert tight > 0.0


# ─── Task 1: windowed / ceilinged / residual-peak-gated deferral (D-16-1) ────


def test_daytime_headroom_does_not_count() -> None:
    """Daytime headroom contributes ZERO deferrable budget (window mask).

    The governed plug-in window DEFERRAL_PLUGIN_WINDOW (18..07) excludes daytime hours
    (08..15). If ALL transformer slack sits in the daytime (the base is at rating
    overnight, with slack only at noon), enrolled EV energy cannot be deferred — the
    window mask zeroes the daytime headroom even though it is numerically generous.
    """
    k, n_steps = 4, 24
    rating = 100.0
    res_minutes = 60
    # Row-1 EV adds 6 kWh in-window (hour 2, inside 18..07).
    pool = np.zeros((k, 2, n_steps), dtype="float64")
    pool[:, 1, 2] = 6.0
    # Base is AT rating every in-window hour (zero overnight headroom) and far below
    # rating only at noon (out of window) — the only slack is daytime, hence masked.
    q = np.full((k, n_steps), rating, dtype="float64")
    q[:, 12] = 10.0  # generous slack, but daytime ⇒ masked to zero headroom
    out = undeliverable_energy(q, pool, 1, rating, res_minutes, enrollment_fraction=1.0)
    # All 6 kWh enrolled is undeliverable: the only headroom is masked-out daytime slack.
    assert out == pytest.approx(6.0)


def test_per_charger_ceiling_binds() -> None:
    """Deliverable energy is capped at n_enrolled · ceiling · window-hours · res/60.

    When the per-charger ceiling × n_enrolled is smaller than the windowed headroom the
    ceiling binds: only n_enrolled · DEFERRAL_CHARGER_KW_CEILING kW can flow per step.
    """
    k, n_steps = 4, 24
    rating = 1000.0  # enormous headroom so ONLY the per-charger ceiling can bind
    res_minutes = 60
    # n_ev = 1, full enrollment ⇒ n_enrolled = 1; demand 100 kWh in one in-window hour.
    pool = np.zeros((k, 2, n_steps), dtype="float64")
    pool[:, 1, 2] = 100.0  # hour 2 is inside the 18..07 plug-in window
    q = np.full((k, n_steps), 10.0, dtype="float64")
    out = undeliverable_energy(q, pool, 1, rating, res_minutes, enrollment_fraction=1.0)
    # Deliverable is capped at 1 · 7.2 kW over 14 window-hours = 100.8 kWh >= 100 ⇒ 0.
    # Make the ceiling bind by demanding more than the windowed ceiling budget can pass.
    pool[:, 1, 2] = 200.0  # 200 kWh; ceiling budget = 7.2 · 14 = 100.8 kWh
    out_bind = undeliverable_energy(
        q, pool, 1, rating, res_minutes, enrollment_fraction=1.0
    )
    assert out == pytest.approx(0.0)
    assert out_bind == pytest.approx(200.0 - 7.2 * 14)


def test_residual_peak_is_hard_gate() -> None:
    """A residual (Q + un-enrolled EV) peak over rating is a hard infeasibility gate.

    Even with generous off-peak headroom, an un-enrolled EV that pushes the residual
    peak above rating contributes its over-rating energy to the undeliverable total
    (the un-enrolled chargers are not managed / cannot be power-limited).
    """
    k, n_steps = 4, 24
    rating = 20.0
    res_minutes = 60
    # n_ev = 4, enrollment 0.30 ⇒ n_enrolled = round(1.2) = 1, n_unenrolled = 3.
    pool = np.zeros((k, 5, n_steps), dtype="float64")
    for n in range(1, 5):
        block = np.zeros(n_steps, dtype="float64")
        block[20] = 10.0 * n  # cumulative: n EVs each 10 kW at hour 20 (in window)
        pool[:, n, :] = block[None, :]
    q = np.full((k, n_steps), 5.0, dtype="float64")
    out = undeliverable_energy(
        q, pool, 4, rating, res_minutes, enrollment_fraction=0.30
    )
    # Residual peak = 5 (base) + (3/4)·40 = 35 kW > 20 rating ⇒ 15 kW over-rating energy
    # enters the undeliverable total ⇒ strictly positive.
    assert out > 0.0


def test_sub_hourly_grid_located_valueerror() -> None:
    """A non-24-step grid raises a located ValueError (hour-of-day window misalign)."""
    k, n_steps = 4, 48  # sub-hourly ⇒ step index != hour-of-day
    pool = np.zeros((k, 2, n_steps), dtype="float64")
    pool[:, 1, 0] = 2.0
    q = np.full((k, n_steps), 10.0, dtype="float64")
    with pytest.raises(ValueError, match="n_steps"):
        undeliverable_energy(q, pool, 1, 50.0, 30, enrollment_fraction=0.30)


# ─── ECON-03: pinned-seed byte-stability of the deferral count ───────────────


def test_byte_stability() -> None:
    """Two deferral-count runs on the same fixture give identical content."""
    pool = _toy_pool()
    q = _toy_q_real()
    args = dict(enrollment_fraction=0.30)
    out_a = deferral_hosting_count(q, pool, 18.0, TOL_FRACTION, 6, 60, **args)
    out_b = deferral_hosting_count(q, pool, 18.0, TOL_FRACTION, 6, 60, **args)
    assert out_a["flexible_ev_count"] == out_b["flexible_ev_count"]
    # The flexible count is gated on the firm-consistent infeasibility tolerance
    # (P(infeasible) <= FIRM_PCONG_TOLERANCE), NOT the undeliverable fraction.
    assert out_a["threshold_convention"] == "p_infeasible_le_firmtol"
    assert out_a["pcong_tolerance"] == pytest.approx(float(FIRM_PCONG_TOLERANCE))
    # The binding P(infeasible) curve is byte-stable and monotone non-decreasing over
    # the nested cumulative pool (each added EV can only raise the infeasibility tail).
    p_a = np.asarray(out_a["p_infeasible_curve"], dtype="float64")
    p_b = np.asarray(out_b["p_infeasible_curve"], dtype="float64")
    np.testing.assert_array_equal(p_a, p_b)
    assert bool(np.all(np.diff(p_a) >= -1e-12))
    # The reported feasibility-ceiling diagnostic (undeliverable fraction) is also stable.
    curve_a = np.asarray(out_a["undeliverable_fraction_curve"], dtype="float64")
    curve_b = np.asarray(out_b["undeliverable_fraction_curve"], dtype="float64")
    np.testing.assert_array_equal(curve_a, curve_b)
    assert bool(np.all(np.diff(curve_a) >= -1e-12))


# ─── ECON-03: located ValueErrors ────────────────────────────────────────────


def test_located_valueerror() -> None:
    """rating_kw<=0 / enrollment out of (0,1] / discount_rate<=0 raise located errors."""
    pool = _toy_pool()
    q = _toy_q_real()
    with pytest.raises(ValueError, match="rating_kw"):
        undeliverable_energy(q, pool, 4, 0.0, 60)
    with pytest.raises(ValueError, match="enrollment_fraction"):
        undeliverable_energy(q, pool, 4, 50.0, 60, enrollment_fraction=1.5)
    with pytest.raises(ValueError, match="discount_rate"):
        crf(0.0, LIFE_YEARS)


# ─── Task 2: governed-ensemble headline (enrollment 0.30 -> flex 6, +100%) ───


@pytest.mark.skipif(
    not _project_cache_ready(),
    reason=(
        "ev_hosting_flex Phase-13 design-day .npy (q_real.npy / ev_pool_design.npy) "
        "not present; run generate_design_day_mc.py in the MAIN tree first (gitignored "
        "cache, skipif-skips in CI)"
    ),
)
def test_governed_headline_flex_6() -> None:
    """Governed reproduce-and-pin: deferral flex == 6 at enrollment 0.30 (+100% vs firm 3).

    Loads the SAME governed seed-42 K=60 design-day ensemble the firm count (= 3) is
    pinned against and asserts the D-16-2a headline: at the governed
    ``DEFERRAL_ENROLLMENT_FRACTION`` the firm-consistent deferral gate
    (``P(infeasible) <= FIRM_PCONG_TOLERANCE``, the gate-basis correction) lands the
    flexible count at exactly 6 EVs — firm 3 -> flex 6, +100%. Enrollment is the single
    binding lever (spike provenance: 0.30 -> 6, 0.50 -> 8, 0.60 -> 13). Uses config
    constants (no magic literals): ``TRANSFORMER_KVA``/``POWER_FACTOR`` (71.25 rating),
    ``TOL_FRACTION`` (reported diagnostic), ``FIRM_PCONG_TOLERANCE`` (the binding gate),
    ``DEFERRAL_ENROLLMENT_FRACTION``.
    """
    q_real = np.load(_PROJECT_DATA_DIR / "q_real.npy").astype("float64")
    ev_pool = np.load(_PROJECT_DATA_DIR / "ev_pool_design.npy").astype("float64")
    ev_max = int(ev_pool.shape[1] - 1)

    out = deferral_hosting_count(
        q_real,
        ev_pool,
        _RATING_KW,
        TOL_FRACTION,
        ev_max,
        DESIGN_DAY_RES_MINUTES,
        enrollment_fraction=DEFERRAL_ENROLLMENT_FRACTION,
    )

    assert out["threshold_convention"] == "p_infeasible_le_firmtol"
    assert out["pcong_tolerance"] == pytest.approx(float(FIRM_PCONG_TOLERANCE))
    # The D-16-2a headline, option-B re-pin (2026-07-06): on the physical 75 kVA /
    # 6-home twin the governed firm is 6 and the deferral gate lands flex 12 —
    # the +100% headline ratio is unchanged (was firm 3 -> flex 6).
    assert out["flexible_ev_count"] == 12, (
        f"governed deferral flex={out['flexible_ev_count']} (expected 12 at enrollment "
        f"{DEFERRAL_ENROLLMENT_FRACTION}); the firm-consistent infeasibility gate "
        "reproduces +100% — do NOT weaken the assertion or re-tune the calibration"
    )
    # Gate self-consistency: P(infeasible) at the flex count is within tolerance and
    # the next count exceeds it (the binding crossing sits between flex 12 and 13).
    p_curve = out["p_infeasible_curve"]
    assert p_curve[12] <= float(FIRM_PCONG_TOLERANCE) + 1e-9, p_curve
    assert p_curve[13] > float(FIRM_PCONG_TOLERANCE), p_curve
