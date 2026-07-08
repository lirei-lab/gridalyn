"""Unit + governed tests for the clustered-adoption stage (Study 3B).

Three tiers, mirroring the project convention:
1. HAND-COMPUTED KERNEL TESTS — gini / draw_clustered_adoption /
   apply_local_curtailment, cache-free.
2. MINI-NET CONVERGENCE — a small hand-built full net through the per-draw
   solve helper.
3. GOVERNED REPRODUCE-AND-PIN — reads the emitted clustered_adoption.json
   (skipif absent) and asserts the penalty/recovery invariants.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from projects.ev_hosting_flex.scripts._powerflow import gini


def test_gini_hand_computed() -> None:
    """Gini is 0 for a uniform vector and rises with concentration."""
    assert gini(np.array([5.0, 5.0, 5.0, 5.0])) == pytest.approx(0.0, abs=1e-12)
    # all mass on one element of n -> (n-1)/n
    assert gini(np.array([0.0, 0.0, 0.0, 4.0])) == pytest.approx(0.75, abs=1e-9)
    # known value: [1,2,3,4] -> 0.25
    assert gini(np.array([1.0, 2.0, 3.0, 4.0])) == pytest.approx(0.25, abs=1e-9)
    assert gini(np.array([0.0, 0.0])) == 0.0  # degenerate: zero sum


def test_draw_clustered_adoption_mean_preserving_and_monotone() -> None:
    """delta=0 gives uniform; fleet is preserved; Gini rises with dispersion."""
    from projects.ev_hosting_flex.scripts._powerflow import draw_clustered_adoption

    rng = np.random.default_rng(42)
    homes = np.array([6, 6, 8, 4, 10, 5, 7, 3, 6, 9], dtype=float)
    mu = 1.0

    # delta = 0 -> exactly uniform
    a0 = draw_clustered_adoption(homes, mu, 0.0, rng)
    assert np.allclose(a0, mu)

    # home-weighted mean (fleet / homes) preserved for every dispersion
    ginis = []
    for delta in (0.0, 0.35, 0.7, 1.1):
        acc = []
        for _ in range(200):
            a = draw_clustered_adoption(homes, mu, delta, rng)
            fleet_mean = float(np.sum(a * homes) / homes.sum())
            assert fleet_mean == pytest.approx(mu, rel=1e-9)
            assert np.all(a >= 0.0)
            acc.append(gini(a))
        ginis.append(float(np.mean(acc)))
    # mean Gini strictly increases with dispersion
    assert ginis == sorted(ginis)
    assert ginis[0] == pytest.approx(0.0, abs=1e-12)
    assert ginis[-1] > 0.1


def test_draw_clustered_adoption_respects_cap() -> None:
    """The cap is enforced for EVERY transformer while the fleet stays exact.

    High dispersion on a skewed homes vector is exactly where the naive
    cap-then-rescale would push capped transformers back over the cap; the
    water-fill must hold BOTH the cap and the fleet.
    """
    from projects.ev_hosting_flex.scripts._powerflow import draw_clustered_adoption
    from projects.ev_hosting_flex.scripts.config import CLUSTER_MAX_RATE

    rng = np.random.default_rng(7)
    homes = np.array([12, 1, 1, 1, 2, 3, 10, 1, 1, 8], dtype=float)
    mu = 1.0
    hit_cap = False
    for _ in range(300):
        a = draw_clustered_adoption(homes, mu, 1.1, rng)
        assert np.all(a <= CLUSTER_MAX_RATE + 1e-9), f"cap violated: max {a.max()}"
        assert float(np.sum(a * homes) / homes.sum()) == pytest.approx(mu, rel=1e-9)
        hit_cap = hit_cap or bool(np.any(a >= CLUSTER_MAX_RATE - 1e-9))
    assert hit_cap, "cap never bound — test not exercising the water-fill path"


def test_apply_local_curtailment_caps_to_rating() -> None:
    """EV is shed only above headroom; below the rating nothing is curtailed."""
    from projects.ev_hosting_flex.scripts._powerflow import apply_local_curtailment

    base = np.array([60.0, 40.0, 71.0], dtype=float)   # kW at the trafo
    ev = np.array([20.0, 10.0, 5.0], dtype=float)
    rating = 71.25
    served, curtailed_kwh = apply_local_curtailment(base, ev, rating)
    # hour 0: headroom 11.25 -> serve 11.25, shed 8.75
    # hour 1: headroom 31.25 -> serve all 10, shed 0
    # hour 2: headroom 0.25 -> serve 0.25, shed 4.75
    assert served == pytest.approx([11.25, 10.0, 0.25])
    assert curtailed_kwh == pytest.approx(8.75 + 0.0 + 4.75)
    # a trafo entirely under rating curtails nothing
    served2, c2 = apply_local_curtailment(
        np.array([10.0, 10.0]), np.array([5.0, 5.0]), 71.25
    )
    assert c2 == pytest.approx(0.0)
    assert served2 == pytest.approx([5.0, 5.0])


def test_solve_worst_trafo_mini_net() -> None:
    """A 2-transformer hand-built net solves; curtailment lowers the worst load."""
    import pandapower as pp

    from projects.ev_hosting_flex.scripts.pipeline.analyze_clustered_adoption import (
        _solve_worst_trafo,
    )

    net = pp.create_empty_network()
    b_mv = pp.create_bus(net, vn_kv=25.0)
    pp.create_ext_grid(net, bus=b_mv, vm_pu=1.0)
    lv_trafos = []
    per_trafo_base, per_trafo_homes, load_bus_to_trafo = {}, {}, {}
    for homes in (6, 6):
        b_lv = pp.create_bus(net, vn_kv=0.24)
        t = pp.create_transformer_from_parameters(
            net, hv_bus=b_mv, lv_bus=b_lv, sn_mva=0.075, vn_hv_kv=25.0,
            vn_lv_kv=0.24, vk_percent=2.0, vkr_percent=1.2, pfe_kw=0.25,
            i0_percent=0.4,
        )
        b_h = pp.create_bus(net, vn_kv=0.24)
        pp.create_line_from_parameters(
            net, from_bus=b_lv, to_bus=b_h, length_km=0.02, r_ohm_per_km=0.3,
            x_ohm_per_km=0.08, c_nf_per_km=0.0, max_i_ka=0.4,
        )
        pp.create_load(net, bus=b_h, p_mw=0.0)
        lv_trafos.append(t)
        per_trafo_base[t] = np.full(24, 55.0)  # kW aggregate base
        per_trafo_homes[t] = homes
        load_bus_to_trafo[b_h] = t
    lv_trafos = np.array(lv_trafos)
    ev = np.full(24, 3.0)  # kW per home per hour
    adoption = np.array([2.0, 0.0])  # trafo 0 heavily adopted, trafo 1 none

    unmanaged = _solve_worst_trafo(
        net, per_trafo_base, per_trafo_homes, load_bus_to_trafo, ev,
        adoption, lv_trafos, curtail=False,
    )
    managed = _solve_worst_trafo(
        net, per_trafo_base, per_trafo_homes, load_bus_to_trafo, ev,
        adoption, lv_trafos, curtail=True,
    )
    assert unmanaged["worst_loading"] > 100.0     # cluster overloads trafo 0
    assert managed["worst_loading"] <= unmanaged["worst_loading"]
    assert managed["curtailed_kwh"] > 0.0
    assert unmanaged["curtailed_kwh"] == 0.0


# ─── 3. Governed reproduce-and-pin (skipif artifacts absent) ─────────────

from projects.ev_hosting_flex.scripts.config import PROJECT_OUTPUTS_DIR  # noqa: E402

_CLUSTER = PROJECT_OUTPUTS_DIR / "json" / "clustered_adoption.json"
_REPORT = PROJECT_OUTPUTS_DIR / "reports" / "clustered_adoption_report.json"
_SKIP = (
    "clustered_adoption.json not present; run analyze_clustered_adoption.py "
    "first (outputs are gitignored)"
)


@pytest.mark.skipif(not _CLUSTER.is_file(), reason=_SKIP)
def test_governed_clustered_adoption() -> None:
    """Clustering worsens the worst hotspot; local flex recovers most; burden concentrates.

    With ~540 transformers the per-transformer first-reinforcement mu is
    degenerate (the worst crosses 100% at the lowest mu even uniformly), so the
    penalty is framed as the worst-loading ratio at a fixed mean rate: clustering
    makes the worst hotspot materially worse (higher loading) even though FEWER
    transformers overload (stress concentrates). Local per-transformer curtailment
    pulls the worst back toward its rating at a real, concentrated cost.
    """
    p = json.loads(_CLUSTER.read_text())
    pen, rec = p["penalty"], p["recovery"]
    # clustering makes the worst transformer materially worse at a fixed fleet
    assert pen["worst_loading_clustered"] > pen["worst_loading_uniform"]
    assert pen["penalty_ratio"] > 1.0
    # local flex pulls the worst hotspot back toward its rating (large reduction)
    assert rec["worst_loading_managed_clustered"] < pen["worst_loading_clustered"]
    assert rec["worst_loading_reduction"] > 0.0
    # recovery has a real, concentrated cost (burden falls on EV-heavy clusters)
    assert rec["curtailed_energy_percent"] > 0.0
    assert 0.0 < rec["burden_gini"] < 1.0
    # eje A: worst loading AND Gini at the fixed mean rate rise with dispersion
    deltas = p["dispersion_grid"]
    mi = p["mu_grid"].index(
        min(p["mu_grid"], key=lambda m: abs(m - p["mean_rate_for_gini_axis"]))
    )
    worst = [
        p["by_dispersion"][f"delta_{d:.2f}"]["worst_loading_by_mu"][mi] for d in deltas
    ]
    ginis = [p["by_dispersion"][f"delta_{d:.2f}"]["gini_at_mean_rate"] for d in deltas]
    assert worst == sorted(worst), f"worst loading not rising with dispersion: {worst}"
    assert ginis == sorted(ginis), f"Gini not rising with dispersion: {ginis}"


@pytest.mark.skipif(not _REPORT.is_file(), reason=_SKIP)
def test_governed_clustered_report_contract() -> None:
    """The stage emits a canonical platform report with the summary keys."""
    from gridalyn.foundation.platform.reports import REQUIRED_REPORT_FIELDS

    report = json.loads(_REPORT.read_text())
    for field_name in REQUIRED_REPORT_FIELDS:
        assert field_name in report, f"missing report field {field_name}"
    for key in ("penalty_ratio", "worst_loading_clustered", "burden_gini"):
        assert key in report["summary"], sorted(report["summary"])
