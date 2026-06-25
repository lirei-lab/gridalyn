"""Unit tests for ``projects/ev_hosting_flex/scripts/_stochastic.py``.

The ~20% genuinely-new model layer of Phase 10.1: the TMY heating-degree base
builder (RECAL-03, D-08), the calibrated stochastic EV K-realization sampler
(RECAL-04, D-05/D-13), and the byte-stable Monte-Carlo reducers including
``mc_p95`` (RECAL-06/RECAL-11, D-07). These tests anchor the design-cold
per-home peak to ADMD, prove warm-hour zero-heating, pin the loud TMY-CSV
validation, and lock the seeded-RNG byte-stability contract (a recorded sha256
golden so any RNG-order drift trips CI — Pitfall 2) and the
``interpolation="linear"`` P95 (Pitfall 1).

GUARD-02: the module under test must not ``import pandapower`` / ``geopandas`` /
``lightsim2grid`` at module scope; these tests touch only numpy arrays + the
committed TMY CSV.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
import pytest

from projects.ev_hosting_flex.scripts._stochastic import (
    blend_ev_aggregate,
    ev_realizations,
    mc_p95,
    tmy_base,
    tmy_start_hod,
)
from projects.ev_hosting_flex.scripts.config import (
    ADMD_KW,
    BG_KW,
    EV_COINCIDENCE_RHO,
    PLUGIN_PROB,
    R_THERM,
    SEED,
    T_BALANCE,
    TMY_INPUT_PATH,
)

# ─────────────────────────── TMY base (Task 1) ───────────────────────────


def _occ(hour: float) -> float:
    """Reference occupancy shape (matches the kernel's private ``_occ``)."""
    return 0.7 + 0.3 * np.exp(-0.5 * ((hour - 19.0) / 4.0) ** 2)


def test_tmy_base_shape_and_dtype() -> None:
    """``tmy_base`` returns a float64 ``(n_bus, 8760)`` addressable-per-bus array."""
    nameplate_share = np.array([1.0, 2.0], dtype="float64")
    base = tmy_base(nameplate_share)
    assert base.shape == (2, 8760)
    assert base.dtype == np.dtype("float64")
    # Addressable per bus: bus 1 (share 2.0) is exactly 2x bus 0 (share 1.0).
    np.testing.assert_allclose(base[1], 2.0 * base[0], rtol=0, atol=1e-12)


def test_tmy_base_design_cold_peak_anchored_to_admd() -> None:
    """At the design-cold hour the per-home peak lands in the 6.0-7.5 kW band."""
    base = tmy_base(np.array([1.0], dtype="float64"))
    per_home = base[0]  # share 1.0 -> per-home kW
    # Design-cold peak is the annual maximum of the per-home base.
    peak = float(per_home.max())
    assert 6.0 <= peak <= 7.5, f"design-cold per-home peak {peak} outside [6.0, 7.5]"
    # Sanity: the ADMD anchor (6.5 kW) sits inside the realized band.
    assert peak >= ADMD_KW - 1.0


def test_tmy_base_warm_hour_zero_heating() -> None:
    """A warm hour (temp >= T_BALANCE) equals ``BG_KW * _occ(hod)`` exactly."""
    df = pd.read_csv(TMY_INPUT_PATH).iloc[:8760].copy()
    temp = df["temp_air"].to_numpy("float64")
    hod = df["timestamp"].astype(str).str.slice(11, 13).astype(int).to_numpy()
    warm = np.where(temp >= T_BALANCE)[0]
    assert warm.size > 0, "TMY has no hour at/above the balance point to test"
    h = int(warm[0])
    base = tmy_base(np.array([1.0], dtype="float64"))
    expected = BG_KW * _occ(hod[h])
    assert base[0, h] == pytest.approx(expected, abs=1e-12)


def test_tmy_base_heating_degree_form() -> None:
    """A representative cold hour equals ``BG_KW*_occ + max(0, Tb - T)/R_THERM``."""
    df = pd.read_csv(TMY_INPUT_PATH).iloc[:8760].copy()
    temp = df["temp_air"].to_numpy("float64")
    hod = df["timestamp"].astype(str).str.slice(11, 13).astype(int).to_numpy()
    cold = int(np.argmin(temp))
    base = tmy_base(np.array([1.0], dtype="float64"))
    heat = max(0.0, T_BALANCE - temp[cold]) / R_THERM
    expected = BG_KW * _occ(hod[cold]) + heat
    assert base[0, cold] == pytest.approx(expected, abs=1e-12)


def test_tmy_base_missing_column_raises_located_error() -> None:
    """A TMY missing ``temp_air`` raises a located + remediating ValueError."""
    bad = pd.DataFrame({"timestamp": ["x"] * 8760, "ghi": [0.0] * 8760})
    with pytest.raises(ValueError) as exc:
        tmy_base(np.array([1.0], dtype="float64"), df=bad)
    msg = str(exc.value)
    assert "temp_air" in msg
    assert "Remediation:" in msg


def test_tmy_base_short_rows_raises_located_error() -> None:
    """A short (<8760 rows) TMY raises a located + remediating ValueError."""
    short = pd.DataFrame(
        {"timestamp": ["1989-01-01 00:00:00-05:00"] * 10, "temp_air": [0.0] * 10}
    )
    with pytest.raises(ValueError) as exc:
        tmy_base(np.array([1.0], dtype="float64"), df=short)
    msg = str(exc.value)
    assert "8760" in msg
    assert "Remediation:" in msg


# ──────────────────── stochastic EV sampler + mc_p95 (Task 2) ─────────────

# Golden digest recorded for the small-K configuration below, at the LEGACY
# midnight phase (``start_hod=0``). Any change to the pinned RNG draw order
# (random -> choice -> lognormal -> normal) or the K stack canonicalization trips
# this literal (Pitfall 2 / D-13). This digest is PHASE-INDEPENDENT: the CR-01 fix
# only rolls the already-drawn daily shape, so the default-phase draws are byte-
# unchanged and this golden is intentionally LEFT as-is (the draw-order tripwire).
# Recompute deliberately (and document the re-baseline) if the draw order is ever
# intentionally changed.
_GOLDEN_EV_SHA256 = "be7963476d1271b3cf3acf835ea5b60f1d83a856cbcdf3117e24d9cb205dd31e"

# CR-01 deliberate re-baseline tripwire: the SAME small-K stack but PHASED to the
# committed TMY clock (``start_hod=tmy_start_hod()`` == 19), i.e. the live consume-
# time placement. This digest CHANGED deliberately when CR-01 phase-aligned the EV
# stack to the TMY cold-evening base (the EV-evening / cold-evening coincidence the
# study premises). It is recorded so any future regression in the phase roll — or a
# silent reversion to the ~19 h misaligned sum — trips CI. (Pinned to the local
# value of ``tmy_start_hod()``; if the committed TMY's start hour ever changes, the
# phase and this digest must be re-recorded together, with rationale.)
_GOLDEN_EV_SHA256_PHASED_TMY = (
    "c9878731b2b9da4dcfdf27bbe787670aa5f6f738bc1b5debaf01d5b12344f096"
)


def _content_sha256(arr: np.ndarray) -> str:
    """Canonical-bytes sha256 with signed-zero kill (mirrors the pipeline)."""
    canonical = np.ascontiguousarray(arr, dtype="float64") + 0.0
    return hashlib.sha256(canonical.tobytes()).hexdigest()


def test_ev_realizations_shape_and_dtype() -> None:
    """``ev_realizations`` returns a float64 ``(K, n_bus, 8760)`` stack."""
    rng = np.random.default_rng(SEED)
    stack = ev_realizations(rng, 4, n_ev=3, n_bus=2)
    assert stack.shape == (4, 2, 8760)
    assert stack.dtype == np.dtype("float64")


def test_ev_realizations_byte_stable_across_runs() -> None:
    """Two seeded runs with identical inputs produce byte-identical stacks."""
    a = ev_realizations(np.random.default_rng(SEED), 8, n_ev=2, n_bus=2)
    b = ev_realizations(np.random.default_rng(SEED), 8, n_ev=2, n_bus=2)
    assert _content_sha256(a) == _content_sha256(b)


def test_ev_realizations_golden_digest() -> None:
    """The small-K EV stack matches the recorded golden sha256 (Pitfall 2)."""
    stack = ev_realizations(np.random.default_rng(SEED), 8, n_ev=2, n_bus=2)
    assert _content_sha256(stack) == _GOLDEN_EV_SHA256


def test_ev_realizations_phased_golden_digest_cr01() -> None:
    """The TMY-phased small-K stack matches the CR-01 re-baseline golden sha256.

    Pins the live consume-time placement: the EV stack rolled to the committed
    TMY's start hour-of-day (``tmy_start_hod()`` == 19) so the EV evening peak
    coincides with the TMY cold-evening base. This golden CHANGED deliberately with
    the CR-01 fix (the prior code summed base + EV ~19 h out of phase); recording it
    trips CI on any regression of the phase alignment.
    """
    start_hod = tmy_start_hod()
    assert start_hod == 19, "committed TMY start hour-of-day changed; re-record"
    stack = ev_realizations(
        np.random.default_rng(SEED), 8, n_ev=2, n_bus=2, start_hod=start_hod
    )
    assert _content_sha256(stack) == _GOLDEN_EV_SHA256_PHASED_TMY


def test_ev_realizations_plugin_first_draw_skips_some_evs() -> None:
    """With PLUGIN_PROB < 1 some EVs are skipped (plug-in is the FIRST draw)."""
    assert PLUGIN_PROB < 1.0
    # A high-K stack with several EVs: the per-realization totals must vary
    # (some EVs draw rng.random() > PLUGIN_PROB and contribute nothing).
    stack = ev_realizations(np.random.default_rng(SEED), 16, n_ev=4, n_bus=1)
    totals = stack.reshape(16, -1).sum(axis=1)
    assert totals.min() < totals.max()


def test_mc_p95_pinned_interpolation() -> None:
    """``mc_p95`` matches numpy's ``interpolation='linear'`` and does not raise."""
    vec = [float(i) for i in range(1, 101)]
    got = mc_p95(vec)
    want = float(np.percentile(np.asarray(vec, "float64"), 95, interpolation="linear"))
    assert got == pytest.approx(want, abs=0.0)


# ───────────── partial-coincidence blend kernel (260625-lgg) ──────────────


def _coincidence_factor(blended: np.ndarray, ev_unit: np.ndarray, count: int) -> float:
    """Model coincidence factor: aggregate feeder peak / sum of per-EV peaks (over K).

    The aggregate peak is the K-mean of the per-realization annual max of the
    blended feeder draw; the per-EV-peak sum is ``count`` times the K-mean of the
    per-realization annual max of the single-EV unit. CF = 1 at full coincidence
    (every EV identical + simultaneous), < 1 as diversity spreads the peaks.
    """
    agg_peak = float(blended.max(axis=1).mean())
    per_ev_peak_sum = float(count) * float(ev_unit.max(axis=1).mean())
    return agg_peak / per_ev_peak_sum if per_ev_peak_sum > 0 else 0.0


def _unit_stack(k: int = 16, start_hod: int = 0) -> np.ndarray:
    """Return a small ``(K, 8760)`` n_ev=1 per-EV-unit stack (the coincident shape)."""
    return ev_realizations(
        np.random.default_rng(SEED), k, n_ev=1, n_bus=1, start_hod=start_hod
    )[:, 0, :]


def test_blend_shape_dtype_and_zero_count() -> None:
    """``blend_ev_aggregate`` returns float64 ``(K, 8760)``; count=0 is all-zero."""
    unit = _unit_stack(k=8)
    out = blend_ev_aggregate(unit, 4, rho=0.2, seed=SEED)
    assert out.shape == (8, 8760)
    assert out.dtype == np.dtype("float64")
    zero = blend_ev_aggregate(unit, 0, rho=0.2, seed=SEED)
    assert zero.shape == (8, 8760)
    assert float(np.abs(zero).max()) == 0.0


def test_blend_math_matches_explicit_two_term_formula() -> None:
    """The blend equals ``ρ·count·unit + (1−ρ)·independent(count)`` to <= 1e-9."""
    unit = _unit_stack(k=8)
    count, rho = 3, 0.2
    out = blend_ev_aggregate(unit, count, rho=rho, seed=SEED)
    # Rebuild the independent term with the SAME per-count SeedSequence keying.
    rng_count = np.random.default_rng(np.random.SeedSequence([int(SEED), count]))
    independent = ev_realizations(rng_count, 8, n_ev=count, n_bus=1, start_hod=0)[:, 0, :]
    expected = rho * count * unit + (1.0 - rho) * independent
    np.testing.assert_allclose(out, expected, rtol=0, atol=1e-9)


def test_blend_rho_one_reproduces_coincident_bit_for_bit() -> None:
    """``ρ=1`` reproduces the legacy ``count·unit`` path bit-for-bit (sha256 equal)."""
    unit = _unit_stack(k=8)
    count = 5
    out = blend_ev_aggregate(unit, count, rho=1.0, seed=SEED)
    legacy = (unit * float(count)).astype("float64")
    assert _content_sha256(out) == _content_sha256(legacy)


def test_blend_cf_falls_with_diversity_and_configured_rho_in_band() -> None:
    """CF peaks at ρ=1 and falls toward the diversified end; configured ρ in [0.5,0.75].

    The per-realization peak of the convex mixture ``ρ·A + (1−ρ)·B`` is a convex
    function of ρ, so the K-mean CF need not be strictly monotone step-by-step
    (a shallow convex dip near the diversified floor is expected); the LOAD-BEARING
    property is that full coincidence (ρ=1) is the MAXIMUM (CF == 1) and that moving
    to the diversified end drops CF substantially — which is what makes the firm
    rise. The configured ``EV_COINCIDENCE_RHO`` lands the model CF in the cited band.
    """
    unit = _unit_stack(k=256)
    count = 6
    cf_full = _coincidence_factor(
        blend_ev_aggregate(unit, count, rho=1.0, seed=SEED), unit, count
    )
    cf_indep = _coincidence_factor(
        blend_ev_aggregate(unit, count, rho=0.0, seed=SEED), unit, count
    )
    # ρ=1 is full coincidence (CF == 1 exactly) and is the maximum CF.
    assert cf_full == pytest.approx(1.0, abs=1e-9)
    # The diversified end drops CF substantially (the source of the firm rise).
    assert cf_indep < cf_full - 0.2, f"CF did not fall with diversity: {cf_full}->{cf_indep}"
    # Coarse trend across the interior grid: every ρ<1 sits strictly below full.
    for r in (0.8, 0.6, 0.4, 0.2):
        cf_r = _coincidence_factor(
            blend_ev_aggregate(unit, count, rho=r, seed=SEED), unit, count
        )
        assert cf_r < cf_full, f"CF at rho={r} ({cf_r}) not below full coincidence"
    # The configured EV_COINCIDENCE_RHO lands the model CF in the cited band.
    cf_cfg = _coincidence_factor(
        blend_ev_aggregate(unit, count, rho=EV_COINCIDENCE_RHO, seed=SEED),
        unit,
        count,
    )
    assert 0.5 <= cf_cfg <= 0.75, f"configured-rho CF {cf_cfg} outside [0.5, 0.75]"


def test_blend_per_count_byte_stable_same_count() -> None:
    """Two calls for the SAME count (same seed) are byte-identical (D-05/D-13)."""
    unit = _unit_stack(k=8)
    a = blend_ev_aggregate(unit, 7, rho=0.2, seed=SEED)
    b = blend_ev_aggregate(unit, 7, rho=0.2, seed=SEED)
    assert _content_sha256(a) == _content_sha256(b)


def test_blend_independent_of_sweep_order() -> None:
    """Drawing count=4 before count=7 does not change the count=7 result."""
    unit = _unit_stack(k=8)
    direct7 = blend_ev_aggregate(unit, 7, rho=0.2, seed=SEED)
    _ = blend_ev_aggregate(unit, 4, rho=0.2, seed=SEED)  # draw a different count first
    after7 = blend_ev_aggregate(unit, 7, rho=0.2, seed=SEED)
    assert _content_sha256(direct7) == _content_sha256(after7)


def test_blend_rho_validation_out_of_range_raises() -> None:
    """A ρ outside [0, 1] raises a located ValueError (T-lgg-01)."""
    unit = _unit_stack(k=4)
    for bad in (-0.1, 1.5):
        with pytest.raises(ValueError) as exc:
            blend_ev_aggregate(unit, 3, rho=bad, seed=SEED)
        assert "[0, 1]" in str(exc.value)
