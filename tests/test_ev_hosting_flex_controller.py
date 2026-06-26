"""Unit/integration tests for the two-stage day-ahead curtailment CONTROLLER.

Exercises ``projects/ev_hosting_flex/scripts/pipeline/apply_flexibility_contracts.py``
(stage 5, Phase 15 CTRL-01..04 / RETIRE-02): the plan/realize/validate seam, the
out-of-sample reliability evaluation on a FRESH disjoint ``Q_real`` draw, the
adversarial colder-ensemble degradation, the ``a_t <= r_t`` resource-value
invariant, the disjoint-seed non-intersection (plan block vs OOS block vs the
``7919*r`` EV-pool stride), and the reliability-only flexible-count sweep.

The cache-free unit tests hand-build ``(N, n_steps)`` ``q_real`` + ``(N, ev_max+1,
n_steps)`` ev_pool fixtures so they run without the gitignored design-day cache; a
single ``skipif-no-cache`` integration test drives the full governed stage.

GUARD-02: numpy-only at module scope; this test never ``import pandapower``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from projects.ev_hosting_flex.scripts.config import (
    ADV_SEED_OFFSET,
    DESIGN_DAY_EV_MAX,
    EPS_HEADLINE,
    K_DESIGN,
    OOS_N,
    OOS_SEED_OFFSET,
    SEED,
)
from projects.ev_hosting_flex.scripts.pipeline import apply_flexibility_contracts as ctrl

_EV_SEED_STRIDE = 7919  # mirrors _generators._EV_SEED_STRIDE (RESEARCH A1).


def _toy_q_real(n: int = 8, n_steps: int = 24, *, peak: float = 60.0) -> np.ndarray:
    """A tiny ``(n, n_steps)`` building-base ensemble peaking near the rating."""
    rng = np.random.default_rng(0)
    base = np.full((n, n_steps), 30.0, dtype="float64")
    base[:, 17:21] = peak + rng.normal(0.0, 2.0, size=(n, 4))
    return base.astype("float64")


def _toy_ev_pool(
    n: int = 8, ev_max: int = DESIGN_DAY_EV_MAX, n_steps: int = 24
) -> np.ndarray:
    """A nested cumulative ``(n, ev_max+1, n_steps)`` EV pool (row m = first m EVs)."""
    rng = np.random.default_rng(1)
    per_ev = np.zeros((n, ev_max, n_steps), dtype="float64")
    per_ev[:, :, 17:21] = rng.uniform(1.0, 3.0, size=(n, ev_max, 4))
    cum = np.cumsum(per_ev, axis=1)
    zero = np.zeros((n, 1, n_steps), dtype="float64")
    return np.concatenate([zero, cum], axis=1).astype("float64")


# ─── CTRL-01: plan seam — r_t on a Q_design-anchored forecast ensemble ────────


def test_plan_reserve_shape_and_quantile() -> None:
    """plan_reserve returns r_t (n_steps,) = Q_{1-eps} of the planned required."""
    q_design = np.full(24, 40.0, dtype="float64")
    q_design[17:21] = 65.0
    out = ctrl.plan_reserve(
        q_design=q_design,
        n_ev=5,
        feeder_kw=71.25,
        eps=EPS_HEADLINE,
        seed=SEED,
        n_scenarios=K_DESIGN,
    )
    r_t = out["r"]
    assert r_t.shape == (24,)
    assert np.all(r_t >= 0.0)
    # the activation is bounded by the reserve at plan time (a_t <= r_t).
    assert np.all(out["a"] <= r_t[None, :] + 1e-9)


# ─── CTRL-02: realize/validate out-of-sample on a fresh disjoint Q_real ───────


def test_realize_invariant_a_le_r() -> None:
    """activate: a = min(r_t, required_real) so a_t <= r_t everywhere (CTRL-03)."""
    n, n_steps = 8, 24
    q_real = _toy_q_real(n, n_steps)
    ev_pool = _toy_ev_pool(n, DESIGN_DAY_EV_MAX, n_steps)
    r_t = np.full(n_steps, 5.0, dtype="float64")
    out = ctrl.realize_validate(
        r_t=r_t, q_real=q_real, ev_pool=ev_pool, n_ev=6, feeder_kw=71.25
    )
    a = out["a"]
    assert np.all(a <= r_t[None, :] + 1e-9)
    assert np.all(a >= -1e-9)
    assert 0.0 <= out["realized_p_overload"] <= 1.0


def test_realized_p_overload_is_reduction_over_N() -> None:
    """realized_p = mean over N of (any step overloads after activation)."""
    n, n_steps = 6, 24
    # A base + EV total that overloads in exactly 3 of 6 realizations after a
    # zero reserve (no curtailment) -> realized_p == 0.5.
    feeder_kw = 50.0
    q_real = np.full((n, n_steps), 10.0, dtype="float64")
    q_real[:3, 18] = 60.0  # 3 realizations exceed 50 at hour 18
    ev_pool = np.zeros((n, DESIGN_DAY_EV_MAX + 1, n_steps), dtype="float64")
    r_t = np.zeros(n_steps, dtype="float64")  # no reserve -> no curtailment
    out = ctrl.realize_validate(
        r_t=r_t, q_real=q_real, ev_pool=ev_pool, n_ev=0, feeder_kw=feeder_kw
    )
    assert out["realized_p_overload"] == pytest.approx(0.5)


def test_realized_in_band_with_sufficient_reserve() -> None:
    """A reserve >= the worst required drives realized P(overload) to 0 (<= eps)."""
    n, n_steps = 8, 24
    feeder_kw = 50.0
    q_real = np.full((n, n_steps), 10.0, dtype="float64")
    q_real[:, 18] = 60.0  # every realization needs 10 kW curtailed at hour 18
    ev_pool = np.zeros((n, DESIGN_DAY_EV_MAX + 1, n_steps), dtype="float64")
    r_t = np.full(n_steps, 100.0, dtype="float64")  # ample reserve
    out = ctrl.realize_validate(
        r_t=r_t, q_real=q_real, ev_pool=ev_pool, n_ev=0, feeder_kw=feeder_kw
    )
    assert out["realized_p_overload"] <= EPS_HEADLINE


# ─── Disjoint-seed non-intersection (T-15-07, RESEARCH A1) ────────────────────


def test_disjoint_seed_blocks_do_not_intersect() -> None:
    """Plan block, OOS block, ADV block + the 7919*r EV stride are pairwise disjoint."""
    k = K_DESIGN
    n = OOS_N
    # Building/forecast streams keyed seed+r; EV-pool streams keyed seed+7919*r.
    plan_bld = {SEED + r for r in range(k)}
    plan_ev = {SEED + _EV_SEED_STRIDE * r for r in range(k)}
    plan_fcast = {SEED + 1}
    plan = plan_bld | plan_ev | plan_fcast

    oos_seed = SEED + OOS_SEED_OFFSET
    oos = {oos_seed + r for r in range(n)} | {
        oos_seed + _EV_SEED_STRIDE * r for r in range(n)
    } | {oos_seed + 1}

    adv_seed = SEED + ADV_SEED_OFFSET
    adv = {adv_seed + r for r in range(n)}

    assert plan.isdisjoint(oos), "OOS validation seeds intersect the plan block"
    assert plan.isdisjoint(adv), "adversarial seeds intersect the plan block"
    assert oos.isdisjoint(adv), "adversarial seeds intersect the OOS block"


# ─── CTRL-02: adversarial degradation (reported, not gated) ───────────────────


def test_adversarial_degradation_reported() -> None:
    """A colder (higher) Q_real ensemble reports realized_p_adv > realized_p."""
    n, n_steps = 8, 24
    feeder_kw = 50.0
    q_real = np.full((n, n_steps), 10.0, dtype="float64")
    q_real[:, 18] = 48.0  # mostly below rating
    q_real_adv = q_real.copy()
    q_real_adv[:, 18] = 55.0  # colder -> over rating
    ev_pool = np.zeros((n, DESIGN_DAY_EV_MAX + 1, n_steps), dtype="float64")
    r_t = np.zeros(n_steps, dtype="float64")  # no curtailment so the base shows through
    base = ctrl.realize_validate(
        r_t=r_t, q_real=q_real, ev_pool=ev_pool, n_ev=0, feeder_kw=feeder_kw
    )
    adv = ctrl.realize_validate(
        r_t=r_t, q_real=q_real_adv, ev_pool=ev_pool, n_ev=0, feeder_kw=feeder_kw
    )
    assert adv["realized_p_overload"] > base["realized_p_overload"]


# ─── CTRL-03: resource value invariants ───────────────────────────────────────


def test_resource_value_ratio_sane() -> None:
    """E[Sum a]/Sum r is in [0, 1] and a_t <= r_t (resource-value invariants)."""
    q_design = np.full(24, 40.0, dtype="float64")
    q_design[17:21] = 70.0
    plan = ctrl.plan_reserve(
        q_design=q_design,
        n_ev=6,
        feeder_kw=71.25,
        eps=EPS_HEADLINE,
        seed=SEED,
        n_scenarios=K_DESIGN,
    )
    rv = ctrl.resource_value(plan["r"], plan["a"])
    assert np.all(plan["a"] <= plan["r"][None, :] + 1e-9)
    assert 0.0 <= rv["ratio_e_sum_a_over_sum_r"] <= 1.0 + 1e-9
    assert rv["sum_r"] >= 0.0
    assert rv["e_sum_a"] >= 0.0


# ─── CTRL-04: reliability-only flexible-count sweep ───────────────────────────


def test_flexible_sweep_last_in_tolerance() -> None:
    """flexible_ev_count = largest n_ev with realized P(overload) <= eps, no break."""
    # Monotone realized-p curve: [0, 0, 0.02, 0.2, 0.5] over n_ev 0..4 at eps=0.05.
    curve = [0.0, 0.0, 0.02, 0.2, 0.5]
    flexible, p_at = ctrl.flexible_from_curve(curve, eps=0.05)
    assert flexible == 2  # last index with p <= 0.05
    assert p_at == pytest.approx(0.02)


# ─── Integration (cache-dependent) ────────────────────────────────────────────

_CACHE = Path(__file__).parents[1] / "projects" / "ev_hosting_flex" / "outputs"
_HAS_CACHE = (
    (_CACHE / "data" / "q_real.npy").is_file()
    and (_CACHE / "data" / "q_design.npy").is_file()
    and (_CACHE / "json" / "firm_hosting.json").is_file()
)


@pytest.mark.skipif(not _HAS_CACHE, reason="design-day cache absent (gitignored)")
def test_controller_stage_end_to_end() -> None:
    """The full governed controller stage runs and emits a re-baselined headline."""
    report = ctrl.run_stage()
    summary = report["summary"]
    assert summary["firm_ev_count"] == 3  # read, never re-run
    assert summary["flexible_ev_count"] > summary["firm_ev_count"]
    assert summary["hosting_expansion_percent"] > 0.0
    assert summary["realized_p_overload_at_flexible"] <= EPS_HEADLINE
    # adversarial degrades above the non-adversarial realized value (reported).
    assert summary["adversarial_p_overload"] >= summary["realized_p_overload_at_flexible"]
    assert "sum_r" in summary and "e_sum_a" in summary
