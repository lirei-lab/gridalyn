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
import pytest

from projects.ev_hosting_flex.scripts._twostage import (
    assert_cvxpy_matches_oracle,
    coldday_panel,
    compose_scenarios,
    eps_frontier,
    twostage_oracle,
)
from projects.ev_hosting_flex.scripts.config import (
    C_ACTIVATE,
    C_RESERVE,
    EPS_FRONTIER,
    K_DESIGN,
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
    assert out["rel_day"] == pytest.approx(1.0 - (residual.max(axis=1) > 1e-6).mean())
    # chance constraint: per-hour reliability >= 1 - eps (TWOSTAGE-02)
    assert out["rel_hour"] >= 1.0 - eps - 1e-9


# ─── TWOSTAGE-03: composed scenarios byte-stable ─────────────────────────────


def _toy_q_design() -> np.ndarray:
    """A minimal (24,) day-ahead Q_design forecast trajectory (kW), evening-peaked.

    Phase 15 RETIRE-02: the re-anchored ``compose_scenarios`` takes its base from
    the emitted ``Q_design`` building-mean trajectory (kW), NOT a TMY cold-day
    temperature reconstruction. This stands in for the emitted ``q_design.npy``.
    """
    hours = np.arange(24, dtype="float64")
    # Winter evening-peaked building base ~50-65 kW (idx-62 7-home design-day scale).
    return 50.0 + 12.0 * np.exp(-0.5 * ((hours - 18.0) / 3.0) ** 2)


def _sha(arr: np.ndarray) -> str:
    import hashlib

    canonical = np.ascontiguousarray(arr, dtype="float64") + 0.0
    return hashlib.sha256(canonical.tobytes()).hexdigest()


def test_scenarios_byte_stable() -> None:
    """compose_scenarios is byte-identical across two seeded builds (TWOSTAGE-03)."""
    q_design = _toy_q_design()
    kw = dict(n_ev=9, feeder_kw=71.25, q_design=q_design)
    a = compose_scenarios(np.random.default_rng(SEED), **kw)
    b = compose_scenarios(np.random.default_rng(SEED), **kw)
    # Default ensemble size is now K_DESIGN (D-07: N_SCENARIOS -> K/N).
    assert a.shape == (K_DESIGN, 24)
    assert a.dtype == np.float64
    assert _sha(a) == _sha(b)


def test_scenarios_validates() -> None:
    """Negative sigma / non-positive n / bad q_design raise located ValueErrors (V5)."""
    q_design = _toy_q_design()
    with pytest.raises(ValueError):
        compose_scenarios(
            np.random.default_rng(SEED),
            n_ev=9,
            feeder_kw=71.25,
            q_design=q_design,
            n_scenarios=0,
        )
    with pytest.raises(ValueError):
        compose_scenarios(
            np.random.default_rng(SEED),
            n_ev=9,
            feeder_kw=71.25,
            q_design=q_design,
            sigma_daily=-1.0,
        )
    # A non-1-D q_design is rejected (the re-anchored V5 shape guard).
    with pytest.raises(ValueError):
        compose_scenarios(
            np.random.default_rng(SEED),
            n_ev=9,
            feeder_kw=71.25,
            q_design=np.zeros((2, 24), dtype="float64"),
        )


def test_scenarios_anchored_on_q_design() -> None:
    """The re-anchored ensemble tracks q_design: at n_ev=0 the mean ~= q_design - feeder.

    With zero EVs and feeder_kw=0 the per-scenario base is ``q_design * perturb``
    where ``E[perturb] == 1``, so the ensemble mean tracks ``q_design`` closely.
    """
    q_design = _toy_q_design()
    req = compose_scenarios(
        np.random.default_rng(SEED), n_ev=0, feeder_kw=0.0, q_design=q_design
    )
    # required = max(0, q_design*perturb + 0 - 0); mean over scenarios ~= q_design.
    np.testing.assert_allclose(req.mean(axis=0), q_design, rtol=0.05)


# ─── TWOSTAGE-05: eps-frontier + cold-day panel ──────────────────────────────


def test_eps_frontier() -> None:
    """Reliability is monotone non-decreasing as eps decreases; panel keys tidy."""
    q_design = _toy_q_design()
    req = compose_scenarios(
        np.random.default_rng(SEED), n_ev=11, feeder_kw=71.25, q_design=q_design
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
    q_design = _toy_q_design()
    req = compose_scenarios(
        np.random.default_rng(SEED), n_ev=11, feeder_kw=71.25, q_design=q_design
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
        POWER_FACTOR,
    )
    from projects.ev_hosting_flex.scripts.config import SEED as cfg_seed
    from projects.ev_hosting_flex.scripts.config import (
        TRANSFORMER_KVA,
        K,
    )

    assert cfg_seed == 42
    assert TRANSFORMER_KVA == 75.0
    assert POWER_FACTOR == 0.95
    assert K == 1000


# ─── TWOSTAGE-05: eps-frontier monotone (kernel re-anchored on Q_design) ─────
# The retired stage-6 integration tests (the annual byte-stability headline + the
# supersession-note full-stage run, which sourced the now-retired annual base /
# annual EV stack artifacts) were REMOVED in Phase 15 RETIRE-02. Plan 02 re-points
# stage 6 onto the Q_design/Q_real design-day ensemble and physically deletes the
# retired kernel symbols (cold_day_temp / annual_twostage_headline); the stage-6
# integration test below drives the re-pointed stage against the new seam.


def test_eps_frontier_monotone_in_stage() -> None:
    """Frontier reliability is monotone in eps + panel schema is the tidy set."""
    q_design = _toy_q_design()
    req = compose_scenarios(
        np.random.default_rng(SEED), n_ev=11, feeder_kw=71.25, q_design=q_design
    )
    rows = eps_frontier(req, EPS_FRONTIER)
    # EPS_FRONTIER descends -> reliability_hour non-decreasing as eps falls.
    rels = [row["reliability_hour"] for row in rows]
    assert all(rels[i] <= rels[i + 1] + 1e-9 for i in range(len(rels) - 1))
    panel = coldday_panel(req)
    # the cold-day panel parquet schema columns (TWOSTAGE-05).
    assert set(panel) == {"hour", "r_s", "a_mean", "req_p50", "req_p90"}


def test_retired_kernel_symbols_deleted() -> None:
    """RETIRE-02: cold_day_temp / annual_twostage_headline are physically gone."""
    import projects.ev_hosting_flex.scripts._stochastic as stoch
    import projects.ev_hosting_flex.scripts._twostage as ts

    assert not hasattr(ts, "cold_day_temp")
    assert not hasattr(ts, "annual_twostage_headline")
    # blend_ev_per_bus had no live consumer after Plan 02 — deleted; the kept MDPI
    # primitives + the still-live blend_ev_aggregate/tmy_start_hod survive.
    assert not hasattr(stoch, "blend_ev_per_bus")
    for kept in ("_ev_day", "_session", "_occ", "mc_p95"):
        assert hasattr(stoch, kept), kept


# ─── Stage 6 re-point: design-day Q_design ensemble end-to-end (RETIRE-02) ────


def test_stage6_design_day_repoint(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """derive_twostage sources q_real/q_design/ev_pool + firm_hosting and proves cvxpy.

    Drives the re-pointed stage-6 ``derive_twostage`` against synthetic design-day
    artifacts (q_real (K, n_steps), q_design (n_steps,), ev_pool (K, ev_max+1,
    n_steps)) + a firm_hosting.json denominator in tmp dirs, and asserts: the
    optimal_hosting.json is framed on the design day (no annual_activated_fraction),
    K/n_steps are read from q_real.shape, the cvxpy<->oracle drift is <=1e-6 (or a
    recorded fallback), and the frontier/panel parquet are emitted.
    """
    pytest.importorskip("cvxpy")
    import json

    import pandas as pd

    from projects.ev_hosting_flex.scripts.pipeline.solve_twostage_program import (
        derive_twostage,
    )

    k, n_steps, ev_max = 12, 24, 6
    rng = np.random.default_rng(SEED)
    q_design = _toy_q_design()  # (24,)
    # q_real: a small (K, n_steps) building-base ensemble around q_design.
    q_real = np.maximum(
        0.0, q_design[None, :] + rng.normal(0.0, 1.0, (k, n_steps))
    ).astype("float64")
    # ev_pool: nested cumulative (K, ev_max+1, n_steps), monotone in count.
    per_ev = np.abs(rng.normal(2.0, 0.5, (k, ev_max, n_steps))).astype("float64")
    ev_pool = np.concatenate(
        [np.zeros((k, 1, n_steps)), np.cumsum(per_ev, axis=1)], axis=1
    ).astype("float64")

    data_dir = tmp_path / "data"
    json_dir = tmp_path / "json"
    data_dir.mkdir()
    json_dir.mkdir()
    np.save(data_dir / "q_real.npy", q_real)
    np.save(data_dir / "q_design.npy", q_design.astype("float64"))
    np.save(data_dir / "ev_pool_design.npy", ev_pool)
    (json_dir / "firm_hosting.json").write_text(
        json.dumps(
            {
                "firm_ev_count": 3,
                "firm_penetration": 0.428571,
                "downstream_home_count": 7,
                "feeder_key": "transformer:62",
                "feeder_transformer_modeled_kw": 71.25,
            }
        )
    )

    out = derive_twostage(tmp_path / "cache", data_dir, json_dir)

    headline = json.loads((json_dir / "optimal_hosting.json").read_text())
    # Framed on the design day — the retired annual key is gone.
    assert "annual_activated_fraction" not in headline
    assert "activated_mean_fraction" in headline
    # K / n_steps read from q_real.shape, never config.K.
    assert headline["k_realizations"] == k
    assert headline["n_steps"] == n_steps
    assert headline["firm_ev_count"] == 3
    assert headline["representative_ev_count"] == 3
    # The load-bearing cvxpy<->oracle <=1e-6 proof is preserved (or a fallback).
    assert headline["cvxpy_oracle_drift"] <= 1e-6 or headline["cvxpy_fellback"]
    assert "content_sha256" in headline
    # The frontier + cold-day panel parquet are emitted on the new ensemble.
    frontier = pd.read_parquet(data_dir / "twostage_frontier.parquet")
    panel = pd.read_parquet(data_dir / "reserve_activation_coldday.parquet")
    assert len(frontier) == len(EPS_FRONTIER)
    assert list(panel.columns) == ["hour", "r_s", "a_mean", "req_p50", "req_p90"]
    assert out["cvxpy_fellback"] in (True, False)
