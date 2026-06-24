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
    assert out["rel_day"] == pytest.approx(1.0 - (residual.max(axis=1) > 1e-6).mean())
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


# ─── Stage integration tests: solve_twostage_program (Wave 2, 10.2-02) ──────
# These drive the new pipeline stage between apply_flexibility_contracts and
# validate_powerflow. The byte-stable + frontier-monotone tests use small
# synthetic fixtures (no cube, no gitignored cache); the supersession-note test
# drives the full stage against the regenerated project cache and skips cleanly
# when the cache is absent (the MEMORY note: the ev_hosting_flex cache is
# gitignored — regenerate before trusting cache-dependent tests).

import os  # noqa: E402
import shutil  # noqa: E402
from pathlib import Path  # noqa: E402

from projects.ev_hosting_flex.scripts._twostage import (  # noqa: E402
    annual_twostage_headline,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    EPS_HEADLINE,
    PROJECT_OUTPUTS_DIR,
    PROJECT_ROOT,
)
from projects.ev_hosting_flex.scripts.pipeline.solve_twostage_program import (  # noqa: E402
    _content_sha256,
    derive_twostage,
    run_stage,
)

_PROJECT_DATA_DIR = PROJECT_OUTPUTS_DIR / "data"
_PROJECT_JSON_DIR = PROJECT_OUTPUTS_DIR / "json"
_PROJECT_CACHE_DIR = PROJECT_OUTPUTS_DIR / "cache"
_STAGE_REQUIRED = [
    _PROJECT_JSON_DIR / "firm_hosting.json",
    _PROJECT_DATA_DIR / "base_load_8760.parquet",
    _PROJECT_DATA_DIR / "ev_stack_K.npy",
]


def _stage_cache_ready() -> bool:
    """True iff the stage-3 profiles + stage-4 firm_hosting.json are present."""
    return all(p.is_file() for p in _STAGE_REQUIRED)


def _synth_headline_inputs() -> dict:
    """A tiny (n_bus=2, 8760) base + (K=8, 8760) EV fixture for the annual harness.

    Sized so no (365, K, 24) cube is ever materialized — the per-day streaming
    harness consumes it one day at a time.
    """
    rng = np.random.default_rng(SEED)
    n_bus, hours, k = 2, 8760, 8
    base = rng.uniform(5.0, 30.0, size=(n_bus, hours)).astype("float64")
    ev_stack = rng.uniform(0.0, 2.0, size=(k, hours)).astype("float64")
    feeder_indicator = np.ones(n_bus, dtype="float64")
    return {
        "base": base,
        "ev_stack": ev_stack,
        "feeder_indicator": feeder_indicator,
        "feeder_kw": 40.0,
    }


def test_annual_headline_byte_stable() -> None:
    """The annual two-stage headline is byte-stable across two runs (TWOSTAGE-04)."""
    fx = _synth_headline_inputs()
    firm_ev_count, flexible_ev_count = 3, 6

    def _headline() -> dict:
        return annual_twostage_headline(
            fx["base"],
            fx["ev_stack"] * float(flexible_ev_count),
            fx["feeder_indicator"],
            fx["feeder_kw"],
            eps=EPS_HEADLINE,
            downstream_home_count=7,
            firm_ev_count=firm_ev_count,
            flexible_ev_count=flexible_ev_count,
        )

    a = _headline()
    b = _headline()
    arr_a = np.array(
        [
            a["hosting_expansion_percent"],
            a["annual_activated_kwh"],
            a["seasonal_peak_kw"],
        ],
        dtype="float64",
    )
    arr_b = np.array(
        [
            b["hosting_expansion_percent"],
            b["annual_activated_kwh"],
            b["seasonal_peak_kw"],
        ],
        dtype="float64",
    )
    assert _content_sha256(arr_a) == _content_sha256(arr_b)
    # the hosting headline contract: (flexible - firm) / firm, flexible >= firm.
    assert a["flexible_ev_count"] >= a["firm_ev_count"]
    assert a["hosting_expansion_percent"] == pytest.approx(
        (flexible_ev_count - firm_ev_count) / firm_ev_count
    )


def test_eps_frontier_monotone_in_stage() -> None:
    """Frontier reliability is monotone in eps + panel schema is the tidy set."""
    df = _toy_tmy()
    req = compose_scenarios(
        np.random.default_rng(SEED), n_ev=11, n_homes=7, feeder_kw=71.25, df=df
    )
    rows = eps_frontier(req, EPS_FRONTIER)
    # EPS_FRONTIER descends -> reliability_hour non-decreasing as eps falls.
    rels = [row["reliability_hour"] for row in rows]
    assert all(rels[i] <= rels[i + 1] + 1e-9 for i in range(len(rels) - 1))
    panel = coldday_panel(req)
    # the cold-day panel parquet schema columns (TWOSTAGE-05).
    assert set(panel) == {"hour", "r_s", "a_mean", "req_p50", "req_p90"}


@pytest.mark.skipif(
    not _stage_cache_ready(),
    reason=(
        "ev_hosting_flex stage-3 profiles + stage-4 firm_hosting.json not present; "
        "run generate_annual_profiles.py and compute_congestion.py first"
    ),
)
def test_report_supersession_note(tmp_path: Path) -> None:
    """The stage report carries the D-02 supersession note + cvxpy status (TWOSTAGE-06).

    Drives derive_twostage against the regenerated project cache (skipping
    cleanly when the gitignored cache is absent) and asserts the summary carries
    the cvxpy drift/fallback status, then drives run_stage to assert the
    supersession warning string is in validation.warnings.
    """
    pytest.importorskip("cvxpy")
    # Seed a tmp json_dir with the real firm_hosting.json so derive is hermetic.
    shutil.copy2(
        _PROJECT_JSON_DIR / "firm_hosting.json", tmp_path / "firm_hosting.json"
    )
    derived = derive_twostage(_PROJECT_CACHE_DIR, _PROJECT_DATA_DIR, tmp_path)
    summary = derived["summary"]
    # cvxpy<->oracle drift/status surfaced in the summary (TWOSTAGE-06, D-08c).
    assert "cvxpy_oracle_drift" in summary
    assert "cvxpy_fellback" in summary
    assert summary["flexible_ev_count"] >= summary["firm_ev_count"]
    # the supersession note (D-02) mentions the optimal headline replacing curves.
    note = derived["supersession_note"]
    assert "Supersession" in note and "OPTIMAL" in note
    assert "REPLACES" in note and "descriptive" in note

    # run_stage routes the note into validation.warnings via write_report.
    # project_script() discovers project.yaml from cwd; run from the project root.
    cwd = os.getcwd()
    try:
        os.chdir(PROJECT_ROOT)
        report = run_stage(data_dir=_PROJECT_DATA_DIR)
    finally:
        os.chdir(cwd)
    warnings = report["validation"]["warnings"]
    assert any("Supersession" in w and "REPLACES" in w for w in warnings)
