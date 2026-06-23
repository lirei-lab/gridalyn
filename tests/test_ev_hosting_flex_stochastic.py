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
    ev_realizations,
    mc_p95,
    tmy_base,
)
from projects.ev_hosting_flex.scripts.config import (
    ADMD_KW,
    BG_KW,
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

# Golden digest recorded for the small-K configuration below. Any change to the
# pinned RNG draw order (random -> choice -> lognormal -> normal) or the K stack
# canonicalization trips this literal (Pitfall 2 / D-13). Recompute deliberately
# (and document the re-baseline) if the draw order is intentionally changed.
_GOLDEN_EV_SHA256 = "be7963476d1271b3cf3acf835ea5b60f1d83a856cbcdf3117e24d9cb205dd31e"


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
