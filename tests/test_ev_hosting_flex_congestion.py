"""Unit tests for ``projects/ev_hosting_flex/scripts/_congestion.py``.

Exercises the congestion numeric kernel (CONG-01/02/03, D-09/D-10/D-11/D-12)
against a hand-computed 3-element x 4-hour fixture with KNOWN ``elem_kw`` and
KNOWN ``elem_demand`` — including one element-hour sitting EXACTLY at the limit
(loading 100.0) and several strictly above — plus a tiny base/ev_unit/allocation
fixture pinning the firm / first-overload integer counts to +/-1 sweep step.

GUARD-02: the kernel is numpy-only; this test never ``import pandapower``.
"""

from __future__ import annotations

import numpy as np
import pytest

from projects.ev_hosting_flex.scripts._congestion import (
    congestion_metrics,
    downstream_indicator,
    feeder_elements,
    firm_ev_count,
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
        [100.0, 110.0, 90.0, 120.0],   # loading 100,110, 90,120 -> congested h1,h3
        [40.0, 55.0, 60.0, 30.0],      # loading  80,110,120, 60 -> congested h1,h2
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
    assert metrics["n_congested_lines"] == 3        # all three elements ever congested
    assert metrics["congested_line_hours"] == 5     # 2 + 2 + 1 events
    assert metrics["congested_hours_per_year"] == 3  # hours {1, 2, 3}
    assert metrics["peak_overload_kw"] == 20.0      # elem0 h3: 120 - 100
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
    np.testing.assert_allclose(
        loading, [[30.0, 50.0, 70.0], [50.0, 50.0, 50.0]]
    )


def test_feeder_elements_subtree_scope() -> None:
    """feeder_elements returns the transformer + interior lines, sorted (D-A2)."""
    downstream = {
        "transformer:7": [3, 1, 2],     # feeder subtree buses
        "line:5": [1, 2],               # interior (subset of feeder buses)
        "line:2": [2],                  # interior
        "line:9": [1, 2, 99],           # NOT a subset -> excluded
        "transformer:1": [50, 60],      # other feeder -> excluded
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
