"""Unit tests for ``projects/ev_hosting_flex/scripts/_congestion.py``.

Exercises the congestion numeric kernel (CONG-01/02/03, D-09/D-10/D-11/D-12)
against a hand-computed 3-element x 4-hour fixture with KNOWN ``elem_kw`` and
KNOWN ``elem_demand`` — including one element-hour sitting EXACTLY at the limit
(loading 100.0) and several strictly above — plus a tiny base/ev_unit/allocation
fixture pinning the firm / first-overload integer counts to +/-1 sweep step.

GUARD-02: the kernel is numpy-only; this test never ``import pandapower``.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from projects.ev_hosting_flex.scripts._congestion import (
    congestion_metrics,
    downstream_indicator,
    feeder_elements,
    firm_ev_count,
    firm_pcong_count,
    is_congested,
    proxy_loading,
)

# ─── Hand-computed 3-element x 4-hour fixture ────────────────────────────────
# limit = 100.0 (LINE_LOADING_LIMIT_PERCENT). elem_kw and elem_demand pinned so
# every metric is computed by hand below.
_LIMIT = 100.0
_ELEM_KW = np.array([100.0, 50.0, 200.0], dtype="float64")
# elem_demand[ei, h] in kW.
_ELEM_DEMAND = np.array(
    [
        [100.0, 110.0, 90.0, 120.0],  # loading 100,110, 90,120 -> congested h1,h3
        [40.0, 55.0, 60.0, 30.0],  # loading  80,110,120, 60 -> congested h1,h2
        [180.0, 200.0, 150.0, 210.0],  # loading  90,100, 75,105 -> congested h3 only
    ],
    dtype="float64",
)
_LOADING = _ELEM_DEMAND / _ELEM_KW[:, None] * 100.0


def test_is_congested_strict_gt_limit() -> None:
    """A value sitting EXACTLY at the limit is NOT congested (strict >, D-09)."""
    arr = np.array([99.9, 100.0, 100.1], dtype="float64")
    assert list(is_congested(arr)) == [False, False, True]


def test_is_congested_on_fixture_loading() -> None:
    """The boundary 100.0 (elem 2, hour 1) is not flagged; >100 are."""
    flags = is_congested(_LOADING)
    expected = np.array(
        [
            [False, True, False, True],
            [False, True, True, False],
            [False, False, False, True],
        ]
    )
    assert np.array_equal(flags, expected)


def test_congestion_metrics_hand_computed() -> None:
    """All five CONG-02 metrics equal the hand-computed integers/floats."""
    metrics = congestion_metrics(_LOADING, _ELEM_DEMAND, _ELEM_KW, _LIMIT)
    assert set(metrics) == {
        "max_line_loading_percent",
        "n_congested_lines",
        "congested_line_hours",
        "congested_hours_per_year",
        "peak_overload_kw",
    }
    assert metrics["max_line_loading_percent"] == 120.0
    assert metrics["n_congested_lines"] == 3  # all three elements ever congested
    assert metrics["congested_line_hours"] == 5  # 2 + 2 + 1 events
    assert metrics["congested_hours_per_year"] == 3  # hours {1, 2, 3}
    assert metrics["peak_overload_kw"] == 20.0  # elem0 h3: 120 - 100
    # Plain Python int/float for the regression numeric branch.
    assert isinstance(metrics["n_congested_lines"], int)
    assert isinstance(metrics["max_line_loading_percent"], float)


def test_congestion_metrics_invariant() -> None:
    """congested_hours_per_year <= congested_line_hours (Pitfall 2)."""
    metrics = congestion_metrics(_LOADING, _ELEM_DEMAND, _ELEM_KW, _LIMIT)
    assert metrics["congested_hours_per_year"] <= metrics["congested_line_hours"]


def test_proxy_loading_matches_manual_matmul() -> None:
    """proxy_loading does indicator @ demand then /elem_kw*100, float64."""
    # 2 elements over 2 buses, 3 hours.
    indicator = np.array([[1.0, 1.0], [0.0, 1.0]], dtype="float64")
    demand = np.array([[10.0, 20.0, 30.0], [5.0, 5.0, 5.0]], dtype="float64")
    elem_kw = np.array([50.0, 10.0], dtype="float64")
    loading, elem_demand = proxy_loading(indicator, demand, elem_kw)
    assert str(loading.dtype) == "float64"
    assert str(elem_demand.dtype) == "float64"
    # elem0 demand = bus0+bus1 = [15,25,35]; elem1 = bus1 = [5,5,5]
    np.testing.assert_allclose(elem_demand, [[15.0, 25.0, 35.0], [5.0, 5.0, 5.0]])
    np.testing.assert_allclose(loading, [[30.0, 50.0, 70.0], [50.0, 50.0, 50.0]])


def test_feeder_elements_subtree_scope() -> None:
    """feeder_elements returns the transformer + interior lines, sorted (D-A2)."""
    downstream = {
        "transformer:7": [3, 1, 2],  # feeder subtree buses
        "line:5": [1, 2],  # interior (subset of feeder buses)
        "line:2": [2],  # interior
        "line:9": [1, 2, 99],  # NOT a subset -> excluded
        "transformer:1": [50, 60],  # other feeder -> excluded
    }
    elements, feeder_buses = feeder_elements(downstream, "transformer:7")
    assert feeder_buses == [1, 2, 3]
    assert elements == ["transformer:7", "line:2", "line:5"]


def test_downstream_indicator_zero_one_matrix() -> None:
    """downstream_indicator is a 0/1 float64 matrix over SORTED bus_ids."""
    downstream = {
        "transformer:7": [1, 2, 3],
        "line:2": [2],
        "line:5": [1, 2],
    }
    elements = ["transformer:7", "line:2", "line:5"]
    bus_ids = [1, 2, 3]
    indicator = downstream_indicator(elements, bus_ids, downstream)
    assert str(indicator.dtype) == "float64"
    expected = np.array(
        [
            [1.0, 1.0, 1.0],  # transformer:7 -> all buses
            [0.0, 1.0, 0.0],  # line:2 -> bus 2
            [1.0, 1.0, 0.0],  # line:5 -> buses 1,2
        ]
    )
    assert np.array_equal(indicator, expected)


def test_firm_ev_count_last_zero_overload() -> None:
    """firm_ev_count returns the last zero-overload count + the +1 overload count.

    One element over one bus; elem_kw = 100. base = 80 (flat). ev_unit = 1 kW per
    EV per hour at the bus. alloc puts ALL EVs on the single bus. Loading at the
    bus = (80 + total_ev) / 100 * 100 = 80 + total_ev percent.

    Sweep [0, 10, 20, 30]:
      - 0  -> loading 80   (ok)
      - 10 -> loading 90   (ok)
      - 20 -> loading 100  (tie -> NOT congested, strict >)
      - 30 -> loading 110  (overload -> break)
    => firm = 20, first_overload = 30.
    """
    indicator = np.array([[1.0]], dtype="float64")
    elem_kw = np.array([100.0], dtype="float64")
    base = np.full((1, 4), 80.0, dtype="float64")
    ev_unit = np.ones((1, 4), dtype="float64")

    def alloc_fn(total_ev: int) -> np.ndarray:
        return np.array([float(total_ev)], dtype="float64")

    result = firm_ev_count(
        (0, 10, 20, 30), base, ev_unit, alloc_fn, indicator, elem_kw, _LIMIT
    )
    assert result["firm_ev_count"] == 20
    assert result["first_overload_ev_count"] == 30
    assert result["threshold_convention"] == "strict_gt_limit"
    assert list(result["ev_sweep"]) == [0, 10, 20, 30]


def test_firm_ev_count_no_overload_returns_last() -> None:
    """If no swept count overloads, firm = the largest count, first_overload None."""
    indicator = np.array([[1.0]], dtype="float64")
    elem_kw = np.array([1000.0], dtype="float64")
    base = np.full((1, 4), 80.0, dtype="float64")
    ev_unit = np.ones((1, 4), dtype="float64")

    def alloc_fn(total_ev: int) -> np.ndarray:
        return np.array([float(total_ev)], dtype="float64")

    result = firm_ev_count(
        (0, 10, 20), base, ev_unit, alloc_fn, indicator, elem_kw, _LIMIT
    )
    assert result["firm_ev_count"] == 20
    assert result["first_overload_ev_count"] is None


# ─── firm_pcong_count: P(cong) <= 10% over K (D-06), via the kept proxy ───────
# Hand-built single-element / single-bus fixture so P(cong) at each penetration is
# an exactly-countable k/K, and the firm crossing is a hand-computed linear interp.
#
# One element (kW=100) over one bus. base = 80 (flat). alloc_fn returns the
# penetration verbatim as the single-bus EV count. ev_stack[k] is a per-realization
# 1-kW-per-EV unit shape, but with exactly ``k`` of the K realizations carrying a
# +EPS spike that tips an at-limit hour OVER the limit, so the count of congesting
# realizations at a given penetration is controllable.

_FP_LIMIT = 100.0
_FP_INDICATOR = np.array([[1.0]], dtype="float64")
_FP_ELEM_KW = np.array([100.0], dtype="float64")
_FP_BASE = np.full((1, 4), 80.0, dtype="float64")


def _fp_alloc(pen: float) -> np.ndarray:
    """Return the single-bus EV allocation = penetration verbatim."""
    return np.array([float(pen)], dtype="float64")


def _fp_ev_stack(k: int, congest_count: int) -> np.ndarray:
    """Build a (k, 1, 4) EV unit stack where ``congest_count`` realizations spike.

    Every realization carries a flat 1 kW/EV unit demand. The first
    ``congest_count`` realizations additionally carry a +1e-3 kW spike at hour 0 so
    that, once the demand reaches exactly the limit, those (and only those)
    realizations strictly exceed it (strict-> reuse). The remaining realizations sit
    at-or-below the limit at the same penetration.
    """
    stack = np.ones((k, 1, 4), dtype="float64")
    for kk in range(congest_count):
        stack[kk, 0, 0] += 1e-3
    return stack


def test_firm_pcong_count_p_cong_equals_k_over_K() -> None:
    """P(cong) at a penetration equals the k/K of realizations that congest.

    base = 80; at penetration p the unit demand is p kW/bus so loading = 80 + p
    percent. At p = 20 the base reaches exactly the limit (loading 100.0 — NOT
    congested, strict >); the ``congest_count`` spiked realizations tip hour 0 to
    100.001 (congested). With K=10 and congest_count=3, P(cong)=0.3 at p=20.
    """
    K = 10
    ev_stack = _fp_ev_stack(K, congest_count=3)
    result = firm_pcong_count(
        _FP_BASE,
        ev_stack,
        _fp_alloc,
        _FP_INDICATOR,
        _FP_ELEM_KW,
        penetration_sweep=(0.0, 20.0),
        tolerance=0.10,
        limit=_FP_LIMIT,
    )
    # p_cong vector: at p=0 loading 80 (no congestion); at p=20 loading 100 +
    # spike on 3/10 realizations -> P(cong) = 0.3.
    pc = dict(zip(result["penetration_sweep"], result["p_cong"]))
    assert pc[0.0] == 0.0
    assert pc[20.0] == 0.3


def test_firm_pcong_count_linear_interp_crossing() -> None:
    """firm crosses where P(cong) rises through the tolerance via linear interp.

    Two sweep points p=10 (P=0.0) and p=20 (P=0.5); tolerance 0.10. The crossing
    is x0 + (tol - y0)*(x1 - x0)/(y1 - y0) = 10 + (0.10 - 0.0)*(20-10)/(0.5-0.0)
    = 10 + 0.10*10/0.5 = 10 + 2.0 = 12.0.
    """
    K = 10
    # At p=10 loading 90 -> never congested. At p=20 loading 100 + spike on 5/10.
    ev_stack = _fp_ev_stack(K, congest_count=5)
    result = firm_pcong_count(
        _FP_BASE,
        ev_stack,
        _fp_alloc,
        _FP_INDICATOR,
        _FP_ELEM_KW,
        penetration_sweep=(10.0, 20.0),
        tolerance=0.10,
        limit=_FP_LIMIT,
    )
    assert result["p_cong"] == [0.0, 0.5]
    np.testing.assert_allclose(result["firm_penetration"], 12.0)
    assert result["p_cong_at_firm"] <= 0.10 + 1e-12
    assert result["threshold_convention"] == "strict_gt_limit"


def test_firm_pcong_count_at_limit_not_congested() -> None:
    """A loading of EXACTLY the limit is NOT congested in the firm reduction.

    With congest_count=0 (no realization spikes), at p=20 every realization sits at
    exactly 100.0 loading -> strict-> means P(cong) = 0.0, so firm spans the whole
    sweep (all <= tolerance -> firm is the last penetration).
    """
    K = 8
    ev_stack = _fp_ev_stack(K, congest_count=0)
    result = firm_pcong_count(
        _FP_BASE,
        ev_stack,
        _fp_alloc,
        _FP_INDICATOR,
        _FP_ELEM_KW,
        penetration_sweep=(0.0, 10.0, 20.0),
        tolerance=0.10,
        limit=_FP_LIMIT,
    )
    assert result["p_cong"] == [0.0, 0.0, 0.0]
    # All P(cong) <= tolerance -> firm = the largest swept penetration.
    np.testing.assert_allclose(result["firm_penetration"], 20.0)


def test_firm_pcong_count_reuses_is_congested_no_second_epsilon() -> None:
    """firm_pcong_count adds NO bare ``> limit`` threshold of its own (T-10.1-07).

    Reads the kernel source and asserts the function body calls ``is_congested(``
    and contains no bare ``> limit`` / ``>= limit`` comparison (the single-epsilon
    invariant — every threshold decision routes through the kept helper).
    """
    import inspect

    src = inspect.getsource(firm_pcong_count)
    assert "is_congested(" in src
    assert "> limit" not in src
    assert ">= limit" not in src
    assert "> float(limit)" not in src


def test_firm_pcong_count_first_point_above_tol_returns_zero() -> None:
    """If the very first swept penetration already exceeds the tolerance, firm = 0."""
    K = 10
    ev_stack = _fp_ev_stack(K, congest_count=5)  # P(cong)=0.5 at p=20
    result = firm_pcong_count(
        _FP_BASE,
        ev_stack,
        _fp_alloc,
        _FP_INDICATOR,
        _FP_ELEM_KW,
        penetration_sweep=(20.0, 30.0),  # first point already 0.5 > 0.10
        tolerance=0.10,
        limit=_FP_LIMIT,
    )
    assert result["p_cong"][0] == 0.5
    assert result["firm_penetration"] == 0.0


def test_congestion_metrics_rejects_empty_elements() -> None:
    """Empty loading raises a located ValueError (V5 validation)."""
    with pytest.raises(ValueError, match="empty"):
        congestion_metrics(
            np.empty((0, 4), dtype="float64"),
            np.empty((0, 4), dtype="float64"),
            np.empty((0,), dtype="float64"),
            _LIMIT,
        )


def test_proxy_loading_rejects_nonpositive_elem_kw() -> None:
    """A nonpositive elem_kw raises a located ValueError (V5 validation)."""
    indicator = np.array([[1.0]], dtype="float64")
    demand = np.array([[10.0]], dtype="float64")
    with pytest.raises(ValueError, match="elem_kw"):
        proxy_loading(indicator, demand, np.array([0.0], dtype="float64"))


# ─── End-to-end derive_congestion: re-calibrated firm = P(cong)<=tol + P95 (10.1) ─
# The re-calibrated stage 4 reduces over the K-axis to firm = P(cong) <=
# FIRM_PCONG_TOLERANCE (D-06) and reports P95 congestion metrics (D-07), asserting
# the selected feeder is the ~6-home small LV unit (Pitfall 4).

from pathlib import Path  # noqa: E402

from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    FIRM_PCONG_TOLERANCE,
    PROJECT_CACHE_DIR,
    PROJECT_OUTPUTS_DIR,
    TARGET_HOMES,
)
from projects.ev_hosting_flex.scripts.pipeline.compute_congestion import (  # noqa: E402
    derive_congestion,
)

_PROJECT_DATA_DIR = PROJECT_OUTPUTS_DIR / "data"
_REQUIRED_CACHE = [
    "line_transformer_ratings_kw.json",
    "downstream_bus_map.json",
    "feeder_selection.json",
    "node_building_count.json",
    "grid_cache_meta.json",
]
_REQUIRED_PROFILES = [
    "base_load_8760.parquet",
    "ev_load_unit.parquet",
    "ev_stack_K.npy",
]


def _project_cache_ready() -> bool:
    """True iff the stage-2/3 cache + profiles are present in the project outputs."""
    if not all((PROJECT_CACHE_DIR / name).is_file() for name in _REQUIRED_CACHE):
        return False
    return all((_PROJECT_DATA_DIR / name).is_file() for name in _REQUIRED_PROFILES)


@pytest.mark.skipif(
    not _project_cache_ready(),
    reason=(
        "ev_hosting_flex stage-2/3 cache + profiles not present; run "
        "prepare_topology_cache.py + generate_annual_profiles.py first"
    ),
)
def test_derive_congestion_firm_pcong_and_p95(tmp_path: Path) -> None:
    """End-to-end: firm = P(cong)<=tol over K + P95 metrics + ~6-home feeder.

    Runs the re-calibrated derive_congestion against the regenerated project cache +
    stage-3 TMY/stochastic profiles and asserts the probabilistic firm gate, the P95
    headline, and the ~6-home (25/0.4 kV) feeder assertion.
    """
    derived = derive_congestion(PROJECT_CACHE_DIR, _PROJECT_DATA_DIR, tmp_path)
    summary = derived["summary"]

    # The firm gate is the probabilistic P(cong) <= FIRM_PCONG_TOLERANCE crossing.
    assert 0.0 < summary["firm_penetration"] <= 2.0, summary
    assert summary["firm_ev_count"] > 0, summary
    assert summary["p_cong_at_firm"] <= float(FIRM_PCONG_TOLERANCE) + 1e-9, summary
    assert summary["state"] == "p95_firm"

    # The P95 conservative headline is reported.
    assert summary["p95_max_loading_percent"] > 0.0, summary

    # The ~6-home (25/0.4 kV) feeder assertion passed against the regenerated cache.
    feeder_assertion = summary["feeder_assertion"]
    assert feeder_assertion["feeder_voltage_class"] == "25/0.4 kV"
    assert abs(int(feeder_assertion["downstream_home_count"]) - int(TARGET_HOMES)) <= 3

    # The firm_hosting.json carries the firm + p_cong vector + the feeder assertion.
    firm_json = json.loads((tmp_path / "firm_hosting.json").read_text())
    assert firm_json["firm_ev_count"] == summary["firm_ev_count"]
    assert len(firm_json["p_cong"]) == len(firm_json["penetration_sweep"])
    assert firm_json["p_cong_at_firm"] <= float(FIRM_PCONG_TOLERANCE) + 1e-9

    # The metrics JSON carries the five CONG-02 metric names at the P95 state.
    metrics_json = json.loads((tmp_path / "congestion_metrics.json").read_text())
    for name in (
        "max_line_loading_percent",
        "n_congested_lines",
        "congested_line_hours",
        "congested_hours_per_year",
        "peak_overload_kw",
    ):
        assert name in metrics_json, metrics_json
    assert metrics_json["state"] == "p95_firm"

    # Both loading parquets exist with matching shapes.
    p95 = pd.read_parquet(_PROJECT_DATA_DIR / "line_loading_p95.parquet")
    firm = pd.read_parquet(_PROJECT_DATA_DIR / "line_loading_firm.parquet")
    assert p95.shape == firm.shape
