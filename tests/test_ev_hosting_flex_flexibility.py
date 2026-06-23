"""Unit tests for ``projects/ev_hosting_flex/scripts/_flexibility.py``.

Exercises the closed-form cap/curtailment/sweep kernel (FLEX-01/02/03,
D-01..D-10) against hand-computed indicator/demand/ev_demand fixtures with KNOWN
``f_E`` / ``cap_fraction`` / ``curtailed`` — including a feasible case where the
recomputed capped loading sits exactly at the limit, a shared-upstream case
proving the per-node MAX (not summed-per-line) reduction, an infeasible case
where base load alone overloads, the strict-``<`` tolerance boundary, and the
monotonicity-in-N trade-curve guard.

GUARD-02: the kernel is numpy-only; this test never ``import pandapower``.
"""

from __future__ import annotations

import numpy as np
import pytest

from projects.ev_hosting_flex.scripts._flexibility import (
    flex_curtailment,
    flex_metrics,
    flexible_ev_count,
)

_LIMIT = 100.0


# ─── Cap fixture: transformer over 2 buses + interior line over bus 1 ────────
# indicator: transformer:0 -> [bus0, bus1]; line:0 -> [bus1].
_INDICATOR = np.array([[1.0, 1.0], [0.0, 1.0]], dtype="float64")
_ELEM_KW = np.array([100.0, 50.0], dtype="float64")  # transformer, line


def test_flex_curtailment_feasible_relieves_to_limit() -> None:
    """Hand-computed cap brings every element to <= limit (strict >, FLEX-01).

    base: bus0=40, bus1=30; ev: bus0=20, bus1=40; total: bus0=60, bus1=70.
      transformer demand = 130, kW=100 -> 130% congested; f = (130-100)/60 = 0.5
      line        demand = 70,  kW=50  -> 140% congested; f = (70-50)/40  = 0.5
    cap_fraction: bus0 = 0.5 (transformer only); bus1 = max(0.5, 0.5) = 0.5
    curtailed:    bus0 = 20*0.5 = 10; bus1 = 40*0.5 = 20
    capped demand: bus0=50, bus1=50 -> transformer 100%, line 100% (NOT congested).
    """
    base = np.array([[40.0], [30.0]], dtype="float64")
    ev = np.array([[20.0], [40.0]], dtype="float64")
    demand = base + ev
    out = flex_curtailment(_INDICATOR, demand, ev, _ELEM_KW, _LIMIT)

    np.testing.assert_allclose(out["cap_fraction"], [[0.5], [0.5]])
    np.testing.assert_allclose(out["curtailed"], [[10.0], [20.0]])
    assert out["feasible"] is True
    assert out["residual_overload_kw"] == 0.0

    # Recompute capped loading: every element <= limit.
    capped = demand - out["curtailed"]
    elem_demand = _INDICATOR @ capped
    loading = elem_demand[:, 0] / _ELEM_KW * 100.0
    assert np.all(loading <= _LIMIT + 1e-9)


def test_flex_curtailment_node_level_max_not_summed() -> None:
    """Per-node cap is the MAX of f_E over upstream elements, applied once (D-02).

    Shared upstream: transformer (kW=100) over bus0+bus1 AND interior line
    (kW=40) over bus1. base: bus0=10, bus1=10; ev: bus0=10, bus1=80.
      transformer demand = 110, ev = 90 -> 110% congested; f = 10/90 = 0.1111..
      line        demand = 90,  ev = 80 -> 225% congested; f = (90-40)/80 = 0.625
    bus1 sits under BOTH; its cap is max(0.1111, 0.625) = 0.625 (NOT the sum
    0.736). If the kernel summed per shared line the bus1 cap would be wrong.
    """
    indicator = np.array([[1.0, 1.0], [0.0, 1.0]], dtype="float64")
    elem_kw = np.array([100.0, 40.0], dtype="float64")
    base = np.array([[10.0], [10.0]], dtype="float64")
    ev = np.array([[10.0], [80.0]], dtype="float64")
    demand = base + ev
    out = flex_curtailment(indicator, demand, ev, elem_kw, _LIMIT)

    f_trans = (110.0 - 100.0) / 90.0
    f_line = (90.0 - 40.0) / 80.0
    np.testing.assert_allclose(out["cap_fraction"][0, 0], f_trans)
    np.testing.assert_allclose(out["cap_fraction"][1, 0], f_line)  # max, not sum
    assert out["cap_fraction"][1, 0] < f_trans + f_line  # not summed


def test_flex_curtailment_infeasible_clamps_and_flags() -> None:
    """When base alone overloads, feasible=False, residual>0, cap clamped to 1.0.

    Single element (kW=50) over one bus. base=60 (already 120% with ZERO ev),
    ev=10. f_E pre-clamp = (70-50)/10 = 2.0 > 1 -> infeasible; clamp to 1.0;
    curtailed = 10*1.0 = 10; capped demand = 60 -> still 120% -> residual > 0.
    """
    indicator = np.array([[1.0]], dtype="float64")
    elem_kw = np.array([50.0], dtype="float64")
    base = np.array([[60.0]], dtype="float64")
    ev = np.array([[10.0]], dtype="float64")
    demand = base + ev
    out = flex_curtailment(indicator, demand, ev, elem_kw, _LIMIT)

    assert out["feasible"] is False
    assert out["residual_overload_kw"] > 0.0
    np.testing.assert_allclose(out["cap_fraction"], [[1.0]])
    np.testing.assert_allclose(out["curtailed"], [[10.0]])
    # Residual = capped demand (60) - rating (50) = 10 kW.
    np.testing.assert_allclose(out["residual_overload_kw"], 10.0)


def test_flex_curtailment_congested_with_zero_ev_is_infeasible() -> None:
    """A congested element with NO sheddable EV demand is infeasible (D-03/D-07).

    Single element (kW=100) over one bus, base demand=130 (130% congested) with
    ZERO ev. There is nothing to shed, so the overload cannot be relieved:
    feasible must be False and residual must surface the ~30 kW that remains.
    Regression for the ``safe_ev``-guard hole where f_raw is forced to 0 for
    zero-EV elements, so ``congested & (f_raw > 1.0)`` never fired.
    """
    indicator = np.array([[1.0]], dtype="float64")
    elem_kw = np.array([100.0], dtype="float64")
    demand = np.array([[130.0]], dtype="float64")  # base only, no EV
    ev = np.array([[0.0]], dtype="float64")
    out = flex_curtailment(indicator, demand, ev, elem_kw, _LIMIT)

    assert out["feasible"] is False
    np.testing.assert_allclose(out["curtailed"], [[0.0]])  # nothing to shed
    np.testing.assert_allclose(out["residual_overload_kw"], 30.0)


def test_flex_curtailment_rejects_nonpositive_elem_kw() -> None:
    """A nonpositive elem_kw raises a located ValueError (mirror _congestion)."""
    indicator = np.array([[1.0]], dtype="float64")
    demand = np.array([[10.0]], dtype="float64")
    ev = np.array([[5.0]], dtype="float64")
    with pytest.raises(ValueError, match="elem_kw"):
        flex_curtailment(indicator, demand, ev, np.array([0.0], dtype="float64"))


def test_flex_curtailment_rejects_empty_elem_kw() -> None:
    """An empty elem_kw raises a located ValueError."""
    with pytest.raises(ValueError, match="empty"):
        flex_curtailment(
            np.empty((0, 1), dtype="float64"),
            np.array([[10.0]], dtype="float64"),
            np.array([[5.0]], dtype="float64"),
            np.empty((0,), dtype="float64"),
        )


# ─── flex_metrics: reconciliation + activation ──────────────────────────────


def test_flex_metrics_hand_computed_and_keys() -> None:
    """flex_metrics returns the FLEX-02 set with hand-computed values (D-10)."""
    # 2 nodes x 3 hours. curtailed kWh per node-hour.
    curtailed = np.array([[0.0, 10.0, 0.0], [5.0, 5.0, 0.0]], dtype="float64")
    ev_demand = np.array([[0.0, 20.0, 0.0], [10.0, 10.0, 0.0]], dtype="float64")
    node_annual = ev_demand.sum(axis=1)  # [20, 20]
    total_annual = float(ev_demand.sum())  # 40
    m = flex_metrics(
        curtailed, ev_demand, node_annual, total_annual_ev_demand=total_annual
    )
    # total curtailed = 10 + 5 + 5 = 20 kWh -> 0.02 MWh; fraction = 20/40 = 0.5
    assert m["curtailed_energy_mwh"] == 0.02
    assert m["curtailed_energy_fraction"] == 0.5
    # activation: node0 binds at h1 (1 hour); node1 binds at h0,h1 (2 hours) -> 3
    assert m["contract_activation_hours"] == 3
    assert m["contract_activation_hours_per_node"] == [1, 2]
    assert m["n_active_contracts"] == 2
    assert m["max_curtailment_kw"] == 10.0
    assert isinstance(m["n_active_contracts"], int)
    assert isinstance(m["contract_activation_hours"], int)
    # Reconciliation: Σ per-node == total.
    assert sum(m["per_node_curtailed_energy_mwh"]) == m["curtailed_energy_mwh"]


def test_flex_metrics_rejects_negative_per_node_energy() -> None:
    """A forced-negative per-node energy raises a located ValueError (D-10)."""
    curtailed = np.array([[-1.0, 0.0]], dtype="float64")
    ev_demand = np.array([[10.0, 10.0]], dtype="float64")
    with pytest.raises(ValueError, match="negative"):
        flex_metrics(
            curtailed,
            ev_demand,
            ev_demand.sum(axis=1),
            total_annual_ev_demand=20.0,
        )


def test_flex_metrics_rejects_energy_above_node_annual() -> None:
    """Per-node energy above the node's annual EV demand raises (D-10)."""
    curtailed = np.array([[30.0, 0.0]], dtype="float64")  # 30 kWh shed
    ev_demand = np.array([[10.0, 10.0]], dtype="float64")  # node annual = 20
    with pytest.raises(ValueError, match="exceeds"):
        flex_metrics(
            curtailed,
            ev_demand,
            ev_demand.sum(axis=1),
            total_annual_ev_demand=20.0,
        )


def test_flex_metrics_rejects_empty() -> None:
    """Empty curtailed raises a located ValueError."""
    with pytest.raises(ValueError, match="empty"):
        flex_metrics(
            np.empty((0, 3), dtype="float64"),
            np.empty((0, 3), dtype="float64"),
            np.empty((0,), dtype="float64"),
            total_annual_ev_demand=0.0,
        )


def test_flex_metrics_reconciliation_tolerates_per_node_rounding() -> None:
    """Many-node per-node rounding accumulation must not false-trip recon (D-10).

    Each per-node energy is rounded to ROUND_DECIMALS independently, so summing
    n_bus of them drifts from the once-rounded total by up to half a ULP per
    node. With a real feeder's many buses this exceeds a fixed 1e-6 tolerance
    even though the decomposition is exact — the guard must scale with n_bus.

    20 nodes x 1.2349 kWh: Σ round(1.2349/1000, 6) = 20*0.001235 = 0.024700,
    while round(24.698/1000, 6) = 0.024698 — a 2e-6 drift that trips a fixed
    1e-6 guard but is pure rounding noise (relative error ~8e-5), not a
    double/under-count.
    """
    n_bus = 20
    curtailed = np.full((n_bus, 1), 1.2349, dtype="float64")
    node_annual = np.full(n_bus, 1000.0, dtype="float64")  # >> per-node shed
    m = flex_metrics(
        curtailed,
        curtailed,
        node_annual,
        total_annual_ev_demand=float(n_bus * 1000.0),
    )
    drift = abs(sum(m["per_node_curtailed_energy_mwh"]) - m["curtailed_energy_mwh"])
    # The drift is real rounding noise above the old fixed 1e-6 tolerance...
    assert drift > 10.0**-6
    # ...yet bounded by the per-node rounding budget (half a ULP per node).
    assert drift <= (n_bus * 0.5 + 0.5) * 10.0**-6


# ─── flexible_ev_count: sweep, tolerance boundary, monotonicity ─────────────


def _sweep_indicator() -> tuple[np.ndarray, np.ndarray]:
    """One element over one bus, kW=100."""
    return np.array([[1.0]], dtype="float64"), np.array([100.0], dtype="float64")


def test_flexible_ev_count_grid_member_and_expansion() -> None:
    """flexible_ev_count is a swept-grid member and >= a known firm count (D-08).

    One bus, one element kW=100, 1 hour. base=80 (flat). ev_unit=1 kW/EV.
    alloc puts ALL EVs on the bus. At EV count N the demand = 80 + N.
      - Uncapped congested when 80+N > 100, i.e. N > 20.
      - When congested, f_E = (80+N-100)/N = (N-20)/N; curtailed = N*f = N-20 kWh.
        fraction = (N-20)/N. For the curtailed_energy_fraction < 0.01 gate:
          N=20 -> not congested, curtailed 0,    fraction 0      -> PASS
          N=40 -> curtailed 20, fraction 0.5               -> FAIL (> 1%)
      - Firm count (zero overload) is 20; flexible should also be 20 here, and is
        a member of the swept grid.
    """
    indicator, elem_kw = _sweep_indicator()
    base = np.full((1, 1), 80.0, dtype="float64")
    ev_unit = np.ones((1, 1), dtype="float64")

    def alloc_fn(total_ev: int) -> np.ndarray:
        return np.array([float(total_ev)], dtype="float64")

    sweep = (0, 20, 40, 60)
    out = flexible_ev_count(sweep, base, ev_unit, alloc_fn, indicator, elem_kw, _LIMIT)
    assert out["flexible_ev_count"] in sweep  # D-08: grid member
    assert out["flexible_ev_count"] == 20
    assert out["threshold_convention"] == "strict_gt_limit"
    # trade curve has one record per swept point.
    assert [r["ev_count"] for r in out["trade_curve"]] == list(sweep)


def test_flexible_ev_count_strict_tolerance_boundary() -> None:
    """A point at EXACTLY the tolerance is NOT passing (strict <, D-06).

    Construct a fixture where one swept point lands at curtailed_energy_fraction
    exactly == curtailed_fraction_max. One bus, kW=100, base=100 (flat, 1 hour).
    ev_unit=1. At N, demand=100+N, congested when N>0; f=(100+N-100)/N=1.0 always
    -> curtailed=N, fraction = N / N = 1.0. Use curtailed_fraction_max=1.0 so the
    point is at EXACTLY the boundary; strict < excludes it -> no passing point.
    Also confirm a lower max (1.0+eps) would include it.
    """
    indicator, elem_kw = _sweep_indicator()
    base = np.full((1, 1), 100.0, dtype="float64")
    ev_unit = np.ones((1, 1), dtype="float64")

    def alloc_fn(total_ev: int) -> np.ndarray:
        return np.array([float(total_ev)], dtype="float64")

    # N=0 -> not congested, fraction 0 (< boundary, but flexible_ev_count picks
    # the LARGEST passing N). N=20 -> fraction exactly 1.0 == boundary -> excluded.
    out = flexible_ev_count(
        (0, 20),
        base,
        ev_unit,
        alloc_fn,
        indicator,
        elem_kw,
        _LIMIT,
        curtailed_fraction_max=1.0,
    )
    # Only N=0 passes (fraction 0 < 1.0); N=20 at exactly 1.0 is excluded.
    assert out["flexible_ev_count"] == 0


def test_flexible_ev_count_monotonic_curtailment() -> None:
    """Curtailment is non-decreasing across the sweep (SC4)."""
    indicator, elem_kw = _sweep_indicator()
    base = np.full((1, 1), 80.0, dtype="float64")
    ev_unit = np.ones((1, 1), dtype="float64")

    def alloc_fn(total_ev: int) -> np.ndarray:
        return np.array([float(total_ev)], dtype="float64")

    out = flexible_ev_count(
        (0, 40, 80), base, ev_unit, alloc_fn, indicator, elem_kw, _LIMIT
    )
    curt = [r["curtailed_energy_mwh"] for r in out["trade_curve"]]
    assert curt == sorted(curt)  # non-decreasing


def test_flexible_ev_count_monotonicity_guard_raises() -> None:
    """A synthetic non-monotone alloc triggers the located monotonicity guard."""
    indicator, elem_kw = _sweep_indicator()
    base = np.full((1, 1), 80.0, dtype="float64")
    ev_unit = np.ones((1, 1), dtype="float64")

    # Adversarial alloc: assign MORE EVs at the smaller swept count so curtailment
    # decreases as the swept N rises -> the monotonicity tripwire must fire.
    def bad_alloc(total_ev: int) -> np.ndarray:
        mapping = {40: 200.0, 80: 30.0}
        return np.array([mapping.get(total_ev, float(total_ev))], dtype="float64")

    with pytest.raises(ValueError, match="monotonic"):
        flexible_ev_count(
            (40, 80), base, ev_unit, bad_alloc, indicator, elem_kw, _LIMIT
        )


# ─── End-to-end derive_flexibility stage (10-02, FLEX-01/02/03/04) ───────────
# Runs the real stage-5 derive_flexibility against the regenerated project cache +
# stage-3 profiles + the stage-4 firm_hosting.json, asserting the headline +
# capped flexible loading <= the limit + a monotonic trade curve. Skipped (the
# project cache/profiles are gitignored) when the upstream stages have not run.

import json  # noqa: E402
import shutil  # noqa: E402
from pathlib import Path  # noqa: E402

import pandas as pd  # noqa: E402

from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    LINE_LOADING_LIMIT_PERCENT,
    PROJECT_CACHE_DIR,
    PROJECT_OUTPUTS_DIR,
)
from projects.ev_hosting_flex.scripts.pipeline.apply_flexibility_contracts import (  # noqa: E402
    derive_flexibility,
)

_PROJECT_DATA_DIR = PROJECT_OUTPUTS_DIR / "data"
_PROJECT_JSON_DIR = PROJECT_OUTPUTS_DIR / "json"
_REQUIRED_CACHE = [
    "line_transformer_ratings_kw.json",
    "downstream_bus_map.json",
    "feeder_selection.json",
    "node_building_count.json",
]
_REQUIRED_PROFILES = ["base_load_8760.parquet", "ev_load_unit.parquet"]
_REQUIRED_JSON = ["firm_hosting.json"]


def _project_cache_ready() -> bool:
    """True iff the stage-2/3 cache + profiles + stage-4 firm_hosting are present."""
    if not all((PROJECT_CACHE_DIR / name).is_file() for name in _REQUIRED_CACHE):
        return False
    if not all((_PROJECT_DATA_DIR / name).is_file() for name in _REQUIRED_PROFILES):
        return False
    return all((_PROJECT_JSON_DIR / name).is_file() for name in _REQUIRED_JSON)


@pytest.mark.skipif(
    not _project_cache_ready(),
    reason=(
        "ev_hosting_flex stage-2/3 cache + profiles + stage-4 firm_hosting.json "
        "not present; run prepare_topology_cache.py, generate_annual_profiles.py, "
        "and compute_congestion.py first"
    ),
)
def test_derive_flexibility_headline_and_capped_loading(tmp_path: Path) -> None:
    """End-to-end: the headline + capped flexible loading <= limit + monotone curve.

    Runs derive_flexibility against the regenerated project cache + stage-3
    profiles + stage-4 firm_hosting.json into a tmp json_dir (seeded with a copy
    of the real firm_hosting.json, the headline denominator) and asserts: the
    summary carries hosting_expansion_percent and flexible_ev_count >=
    firm_ev_count; the capped line_loading_flex.parquet max loading <= the limit
    (a feasible flexible state); flexible_hosting.json carries the headline keys +
    a trade-curve list; and the trade-curve curtailed energy is monotonic
    non-decreasing in ev_count.
    """
    # derive_flexibility reads firm_hosting.json from json_dir; seed the tmp dir
    # with the real stage-4 output so the run is hermetic w.r.t. its writes.
    shutil.copy2(
        _PROJECT_JSON_DIR / "firm_hosting.json", tmp_path / "firm_hosting.json"
    )

    derived = derive_flexibility(PROJECT_CACHE_DIR, _PROJECT_DATA_DIR, tmp_path)
    summary = derived["summary"]

    assert "hosting_expansion_percent" in summary, summary
    assert summary["flexible_ev_count"] >= summary["firm_ev_count"], summary
    assert summary["firm_ev_count"] > 0, summary
    # The headline equals (flexible - firm) / firm.
    expected = round(
        (summary["flexible_ev_count"] - summary["firm_ev_count"])
        / summary["firm_ev_count"],
        6,
    )
    assert summary["hosting_expansion_percent"] == expected, summary

    # The capped flexible-limit loading is <= the limit (feasible flexible state).
    loading = pd.read_parquet(_PROJECT_DATA_DIR / "line_loading_flex.parquet")
    assert (
        loading.values.max() <= float(LINE_LOADING_LIMIT_PERCENT) + 1e-6
    ), loading.values.max()

    # flexible_hosting.json carries the headline keys + a trade-curve list.
    flexible_json = json.loads((tmp_path / "flexible_hosting.json").read_text())
    for key in (
        "flexible_ev_count",
        "firm_ev_count",
        "hosting_expansion_percent",
        "curtailed_energy_fraction_at_flexible",
        "trade_curve",
    ):
        assert key in flexible_json, flexible_json
    assert isinstance(flexible_json["trade_curve"], list)
    assert flexible_json["trade_curve"], flexible_json

    # The trade-curve curtailed energy is monotonic non-decreasing in ev_count.
    curve = sorted(flexible_json["trade_curve"], key=lambda r: r["ev_count"])
    curtailed = [r["curtailed_energy_mwh"] for r in curve]
    assert curtailed == sorted(curtailed), curtailed

    # contract_activations.parquet is the tidy trade-curve series.
    activations = pd.read_parquet(_PROJECT_DATA_DIR / "contract_activations.parquet")
    assert "ev_count" in activations.columns
    assert "curtailed_energy_mwh" in activations.columns
