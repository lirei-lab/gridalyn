"""Unit tests for ``projects/ev_hosting_flex/scripts/_twostage.py``.

Exercises the two-stage chance-constrained kernel (TWOSTAGE-01..07,
D-01..D-10) against hand-built ``required`` fixtures with KNOWN quantile /
activation / reliability, the byte-stable composed scenario ensemble, the
ε-frontier monotonicity + cold-day panel, the gated cvxpy↔oracle ≤1e-6
equivalence (importorskip), and the locked-10.1-constants guard.

GUARD-02: the kernel is numpy-only at module scope (cvxpy is deferred inside the
solve fn); this test never ``import pandapower``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from projects.ev_hosting_flex.scripts._twostage import (
    assert_cvxpy_matches_oracle,
    cold_day_temp,
    coldday_panel,
    compose_scenarios,
    eps_frontier,
    twostage_oracle,
)
from projects.ev_hosting_flex.scripts.config import (
    C_ACTIVATE,
    C_RESERVE,
    EPS_FRONTIER,
    N_SCENARIOS,
    SEED,
)


def _toy_required() -> np.ndarray:
    """A tiny (5, 24) required fixture with one congested hour (hour 18)."""
    req = np.zeros((5, 24), dtype="float64")
    req[:, 18] = np.array([0.0, 1.0, 2.0, 3.0, 10.0], dtype="float64")
    req[:, 19] = np.array([0.0, 0.0, 0.5, 1.0, 2.0], dtype="float64")
    return req


# ─── TWOSTAGE-01: oracle math ────────────────────────────────────────────────


def test_oracle_math() -> None:
    """r = Q_{1-eps}[required], a = min(r, required), costs use C_RESERVE/C_ACTIVATE."""
    req = _toy_required()
    eps = 0.2
    out = twostage_oracle(req, eps)
    expect_r = np.quantile(req, 1.0 - eps, axis=0, method="linear")
    np.testing.assert_allclose(out["r"], expect_r, atol=1e-12)
    np.testing.assert_allclose(out["a"], np.minimum(expect_r[None, :], req), atol=1e-12)
    # cost conventions (TWOSTAGE-01)
    assert out["reservation_cost"] == pytest.approx(C_RESERVE * expect_r.sum())
    expect_a = np.minimum(expect_r[None, :], req)
    assert out["activation_cost"] == pytest.approx(
        C_ACTIVATE * expect_a.sum(axis=1).mean()
    )
    assert out["activated_mean_kwh"] == pytest.approx(expect_a.sum(axis=1).mean())


def test_oracle_validates_eps_range() -> None:
    """eps outside (0, 1) raises a located ValueError (V5)."""
    req = _toy_required()
    for bad in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(ValueError, match="eps"):
            twostage_oracle(req, bad)


# ─── TWOSTAGE-02: per-hour reliability (D-05) ────────────────────────────────


def test_perhour_reliability() -> None:
    """rel_hour == 1 - (residual>1e-6).mean(); chance constraint holds (>= 1-eps)."""
    # 20 scenarios; in hour 0 exactly 2 of 20 exceed the (1-eps=0.9) reserve.
    n = 20
    req = np.zeros((n, 24), dtype="float64")
    # 18 scenarios at 1.0, 2 at 100.0 -> Q_0.9 sits at 1.0 region; the 2 high ones
    # leave residual after activation capped at the reserve.
    req[:, 0] = np.array([1.0] * 18 + [100.0, 100.0], dtype="float64")
    eps = 0.1
    out = twostage_oracle(req, eps)
    a = np.minimum(out["r"][None, :], req)
    residual = req - a
    assert out["rel_hour"] == pytest.approx(1.0 - (residual > 1e-6).mean())
    assert out["rel_day"] == pytest.approx(
        1.0 - (residual.max(axis=1) > 1e-6).mean()
    )
    # chance constraint: per-hour reliability >= 1 - eps (TWOSTAGE-02)
    assert out["rel_hour"] >= 1.0 - eps - 1e-9


# ─── TWOSTAGE-03: composed scenarios byte-stable ─────────────────────────────


def _toy_tmy() -> pd.DataFrame:
    """A minimal 8760-row TMY frame with a single coldest hour."""
    hours = np.arange(8760)
    temp = 5.0 + 10.0 * np.sin(hours / 24.0)
    temp[5000] = -25.0  # the annual coldest hour
    ts = pd.date_range("1989-12-31 19:00", periods=8760, freq="h")
    return pd.DataFrame({"timestamp": ts.astype(str), "temp_air": temp})


def _sha(arr: np.ndarray) -> str:
    import hashlib

    canonical = np.ascontiguousarray(arr, dtype="float64") + 0.0
    return hashlib.sha256(canonical.tobytes()).hexdigest()


def test_scenarios_byte_stable() -> None:
    """compose_scenarios is byte-identical across two seeded builds (TWOSTAGE-03)."""
    df = _toy_tmy()
    kw = dict(n_ev=9, n_homes=7, feeder_kw=71.25, df=df)
    a = compose_scenarios(np.random.default_rng(SEED), **kw)
    b = compose_scenarios(np.random.default_rng(SEED), **kw)
    assert a.shape == (N_SCENARIOS, 24)
    assert a.dtype == np.float64
    assert _sha(a) == _sha(b)


def test_scenarios_validates() -> None:
    """Negative sigma / non-positive n raise located ValueErrors (V5)."""
    df = _toy_tmy()
    with pytest.raises(ValueError):
        compose_scenarios(
            np.random.default_rng(SEED),
            n_ev=9,
            n_homes=7,
            feeder_kw=71.25,
            df=df,
            n_scenarios=0,
        )
    with pytest.raises(ValueError):
        compose_scenarios(
            np.random.default_rng(SEED),
            n_ev=9,
            n_homes=7,
            feeder_kw=71.25,
            df=df,
            sigma_daily=-1.0,
        )


def test_cold_day_temp() -> None:
    """cold_day_temp returns 24h temp + hod at the annual coldest day."""
    df = _toy_tmy()
    temp, hod = cold_day_temp(df=df)
    assert temp.shape == (24,)
    assert hod.shape == (24,)
    assert float(temp.min()) <= -25.0 + 1e-9


# ─── TWOSTAGE-05: eps-frontier + cold-day panel ──────────────────────────────


def test_eps_frontier() -> None:
    """Reliability is monotone non-decreasing as eps decreases; panel keys tidy."""
    df = _toy_tmy()
    req = compose_scenarios(
        np.random.default_rng(SEED), n_ev=11, n_homes=7, feeder_kw=71.25, df=df
    )
    rows = eps_frontier(req, EPS_FRONTIER)
    assert len(rows) == len(EPS_FRONTIER)
    # EPS_FRONTIER is descending -> reliability_hour non-decreasing
    rels = [row["reliability_hour"] for row in rows]
    assert all(rels[i] <= rels[i + 1] + 1e-9 for i in range(len(rels) - 1))
    panel = coldday_panel(req)
    assert set(panel) == {"hour", "r_s", "a_mean", "req_p50", "req_p90"}
    assert len(panel["hour"]) == 24


# ─── TWOSTAGE-06: gated cvxpy <-> oracle equivalence ─────────────────────────


def test_cvxpy_matches_oracle() -> None:
    """The gated CLARABEL solve reproduces the oracle reserve to <=1e-6 (TWOSTAGE-06)."""
    pytest.importorskip("cvxpy")
    df = _toy_tmy()
    req = compose_scenarios(
        np.random.default_rng(SEED), n_ev=11, n_homes=7, feeder_kw=71.25, df=df
    )
    oracle, meta = assert_cvxpy_matches_oracle(req, 0.1)
    assert meta["drift"] <= 1e-6
    assert meta["cvxpy_status"] == "optimal"
    assert meta["fellback"] is False
    np.testing.assert_allclose(
        oracle["r"], np.quantile(req, 0.9, axis=0, method="linear"), atol=1e-12
    )


# ─── TWOSTAGE-07: locked 10.1 constants unchanged ────────────────────────────


def test_config_locked_unchanged() -> None:
    """The locked 10.1 constants import byte-unchanged (TWOSTAGE-07)."""
    from projects.ev_hosting_flex.scripts.config import (
        K,
        POWER_FACTOR,
        SEED as cfg_seed,
        TRANSFORMER_KVA,
    )

    assert cfg_seed == 42
    assert TRANSFORMER_KVA == 75.0
    assert POWER_FACTOR == 0.95
    assert K == 1000
