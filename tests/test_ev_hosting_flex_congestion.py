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
    firm_transformer_count,
    is_congested,
    is_overloaded,
    p_overload,
    proxy_loading,
    transformer_loading,
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


# ─── End-to-end derive_congestion: design-day transformer firm + risk (CONG-01/02/03) ─
# The Phase-14 retargeted stage 4 loads the Phase-13 q_real.npy / ev_pool_design.npy,
# pins firm = largest EV count with P(transformer loading > 1) <= FIRM_PCONG_TOLERANCE
# over K (last-in-tolerance), and emits transformer_risk.parquet + p_overload_curve.json
# + firm_hosting.json (5-key contract). The governed firm value is confirmed
# EMPIRICALLY from the regenerated cache (RESEARCH A1 / Open Q1).

from pathlib import Path  # noqa: E402

from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    FIRM_PCONG_TOLERANCE,
    POWER_FACTOR,
    PROJECT_CACHE_DIR,
    PROJECT_OUTPUTS_DIR,
    TRANSFORMER_KVA,
)
from projects.ev_hosting_flex.scripts.pipeline.compute_congestion import (  # noqa: E402
    derive_congestion,
)

_PROJECT_DATA_DIR = PROJECT_OUTPUTS_DIR / "data"
_PROJECT_JSON_DIR = PROJECT_OUTPUTS_DIR / "json"
_RATING_KW = float(TRANSFORMER_KVA) * float(POWER_FACTOR)  # 71.25 (pf pinned)
_REQUIRED_CACHE = [
    "downstream_bus_map.json",
    "feeder_selection.json",
    "node_building_count.json",
]
# The Phase-13 design-day MC artifacts the retargeted stage consumes (gitignored;
# regenerate stages 2-3 in the MAIN tree per MEMORY.md — they skipif-skip in CI).
_REQUIRED_NPY = [
    "q_real.npy",
    "ev_pool_design.npy",
]


def _project_cache_ready() -> bool:
    """True iff the stage-2 cache + Phase-13 design-day .npy are present.

    Extends the prior skip helper to check the new transformer-firm inputs
    (q_real.npy / ev_pool_design.npy) instead of the retired annual profiles.
    """
    if not all((PROJECT_CACHE_DIR / name).is_file() for name in _REQUIRED_CACHE):
        return False
    return all((_PROJECT_DATA_DIR / name).is_file() for name in _REQUIRED_NPY)


@pytest.mark.skipif(
    not _project_cache_ready(),
    reason=(
        "ev_hosting_flex stage-2 cache + Phase-13 design-day .npy "
        "(q_real.npy / ev_pool_design.npy) not present; run prepare_topology_cache.py "
        "+ generate_design_day_mc.py in the MAIN tree first (gitignored cache)"
    ),
)
def test_derive_congestion_transformer_firm_and_risk(tmp_path: Path) -> None:
    """End-to-end: design-day transformer firm + risk distribution + 5-key contract.

    Runs the retargeted derive_congestion against the regenerated project cache +
    Phase-13 design-day ensemble and asserts the non-degenerate firm gate, the
    preserved 5-key firm_hosting.json contract, and the CONG-03 risk artifacts.
    """
    derived = derive_congestion(PROJECT_CACHE_DIR, _PROJECT_DATA_DIR, tmp_path)
    summary = derived["summary"]

    # The firm gate is the non-degenerate transformer-overload crossing (1 <= firm <= 9).
    assert 1 <= int(summary["firm_ev_count"]) <= 9, summary
    assert summary["firm_penetration"] > 0.0, summary
    assert summary["p_overload_at_firm"] <= float(FIRM_PCONG_TOLERANCE) + 1e-9, summary
    assert summary["threshold_convention"] == "strict_gt_rating"
    assert summary["feeder_transformer_modeled_kw"] == _RATING_KW

    # firm_hosting.json preserves the 5 downstream keys + the new transformer keys.
    firm_json = json.loads((tmp_path / "firm_hosting.json").read_text())
    for key in (
        "firm_ev_count",
        "firm_penetration",
        "downstream_home_count",
        "feeder_key",
        "feeder_transformer_modeled_kw",
    ):
        assert key in firm_json, firm_json
    assert firm_json["firm_ev_count"] == summary["firm_ev_count"]
    assert len(firm_json["p_overload_curve"]) == len(firm_json["ev_sweep"])
    # Old unread keys must be gone.
    for oldk in ("p_cong", "p_cong_at_firm", "penetration_sweep"):
        assert oldk not in firm_json, firm_json

    # The P(overload) curve JSON carries {ev_count, ev_per_home, p_overload} rows.
    curve = json.loads((tmp_path / "p_overload_curve.json").read_text())
    assert len(curve) == len(firm_json["ev_sweep"])
    assert set(curve[0]) == {"ev_count", "ev_per_home", "p_overload"}

    # The risk distribution parquet carries per-realization peak %rating over K.
    risk = pd.read_parquet(_PROJECT_DATA_DIR / "transformer_risk.parquet")
    assert "peak_pct_rating" in risk.columns
    assert risk.shape[0] == int(summary["k_realizations"])


@pytest.mark.skipif(
    not _project_cache_ready(),
    reason=(
        "ev_hosting_flex Phase-13 design-day .npy "
        "(q_real.npy / ev_pool_design.npy) not present; run generate_design_day_mc.py "
        "in the MAIN tree first (gitignored cache, skipif-skips in CI)"
    ),
)
def test_governed_ensemble_firm_three() -> None:
    """Governed reproduce-and-pin: firm = 3 from the regenerated design-day cache.

    Loads the governed q_real.npy / ev_pool_design.npy, calls firm_transformer_count
    with the pf-pinned rating (71.25), FIRM_PCONG_TOLERANCE, and ev_max from the
    array, and asserts the firm is NON-DEGENERATE (1 <= firm <= 9) AND equals 3 at
    the locked calibration (RESEARCH A1 / Open Q1 — the one number confirmed
    empirically, not assumed). If the governed ensemble lands at 2 or 4 (still
    non-degenerate), that +/-1 is the DOCUMENTED framing shift — relax to the
    empirically-observed value and record it in the SUMMARY / divergence_note; do
    NOT re-tune the locked R_QUEBEC / P_HEAT_QUEBEC calibration to force 3.

    Also confirms stage/kernel agreement: the firm the kernel computes here equals
    the firm the stage wrote to firm_hosting.json.
    """
    q_real = np.load(_PROJECT_DATA_DIR / "q_real.npy").astype("float64")
    ev_pool = np.load(_PROJECT_DATA_DIR / "ev_pool_design.npy").astype("float64")
    ev_max = int(ev_pool.shape[1] - 1)

    result = firm_transformer_count(
        q_real, ev_pool, _RATING_KW, float(FIRM_PCONG_TOLERANCE), ev_max
    )
    firm = int(result["firm_ev_count"])

    # Non-degenerate (neither 0 nor pinned at the ev_max ceiling).
    assert 1 <= firm <= 9, result
    # The locked-calibration headline. Option-B re-pin (2026-07-06): the twin is
    # now PHYSICALLY 75 kVA / 6 homes (was the decoupled 7-home idx-62 unit,
    # firm=3); with one fewer home the base sits at ~71.6% rating and the governed
    # ensemble lands firm=6 (exactly 1.0 EV/home). Calibration (R_QUEBEC /
    # P_HEAT_QUEBEC) untouched, per this test's own re-pin procedure.
    assert firm == 6, (
        f"governed firm={firm} (expected 6 on the physical 75 kVA / 6-home twin); "
        "if this is a non-degenerate +/-1 framing shift, update the pin + record "
        "it in the SUMMARY / divergence_note — do NOT re-tune R_QUEBEC / P_HEAT_QUEBEC"
    )
    # P(overload) at firm must be within tolerance; the next count must exceed it.
    p_curve = result["p_overload_curve"]
    assert p_curve[firm] <= float(FIRM_PCONG_TOLERANCE) + 1e-9, result
    if firm + 1 < len(p_curve):
        assert p_curve[firm + 1] > float(FIRM_PCONG_TOLERANCE), result

    # Stage/kernel agreement: the firm the stage wrote matches what the kernel computes.
    firm_json = json.loads((_PROJECT_JSON_DIR / "firm_hosting.json").read_text())
    assert int(firm_json["firm_ev_count"]) == firm, firm_json


# ─── Phase-14 transformer-overload kernel (CONG-01/02) — cache-free fixtures ──
# Hand-built (K, n_steps) building base + (K, ev_max+1, n_steps) nested cumulative
# EV pool so P(overload) at each EV count is an exactly-countable k/K and the firm
# crossing is hand-computed. The rating is the pf-pinned modeled rating analog.

_TR_RATING = 100.0  # a round rating so loading == q_total / 100 is by-eye exact.


class TestTransformerOverloadKernel:
    """CONG-01/02: strict-> overload boundary + last-in-tolerance firm sweep."""

    def test_transformer_loading_is_q_over_rating(self) -> None:
        """loading = (Σ building + Σ EV) / rating, float64 (CONG-01)."""
        q_total = np.array([[50.0, 100.0, 150.0]], dtype="float64")
        loading = transformer_loading(q_total, _TR_RATING)
        assert str(loading.dtype) == "float64"
        np.testing.assert_allclose(loading, [[0.5, 1.0, 1.5]])

    def test_is_overloaded_strict_gt_rating(self) -> None:
        """A step EXACTLY at rating (loading == 1.0) is NOT overloaded (strict >)."""
        # 99.999 -> below, 100.0 -> exactly at rating (NOT overloaded), 100.001 -> over.
        q_total = np.array([99.999, 100.0, 100.001], dtype="float64")
        flags = is_overloaded(q_total, _TR_RATING)
        assert list(flags) == [False, False, True]

    def test_p_overload_over_k_ensemble(self) -> None:
        """P(overload) = mean over K of any-step overload at EV count n_ev.

        K=4 realizations, 2 steps. base sits at exactly rating (loading 1.0, NOT
        overloaded). The nested EV pool at n_ev=1 adds a +1.0 kW spike on the first
        3 of 4 realizations -> 3/4 = 0.75 overload over K. n_ev=0 adds nothing.
        """
        rating = _TR_RATING
        q_real = np.full((4, 2), rating, dtype="float64")  # loading exactly 1.0
        # ev_pool[:, 0, :] = 0 (no EV); ev_pool[:, 1, :] spikes first 3 realizations.
        ev_pool = np.zeros((4, 2, 2), dtype="float64")
        ev_pool[:3, 1, 0] = 1.0  # tips loading > 1 on 3/4 realizations at n_ev=1
        assert p_overload(q_real, ev_pool, 0, rating) == 0.0  # at-rating, strict >
        assert p_overload(q_real, ev_pool, 1, rating) == 0.75

    def test_p_overload_reads_k_from_array_not_config(self) -> None:
        """P(overload) is averaged over q_real.shape[0], never config.K (=1000)."""
        rating = _TR_RATING
        # Only K=5 realizations; if the kernel used config.K=1000 the mean would be
        # diluted to 3/1000 instead of 3/5.
        q_real = np.full((5, 2), rating, dtype="float64")
        ev_pool = np.zeros((5, 2, 2), dtype="float64")
        ev_pool[:3, 1, 0] = 1.0
        assert q_real.shape[0] == 5
        np.testing.assert_allclose(p_overload(q_real, ev_pool, 1, rating), 3.0 / 5.0)

    def test_firm_transformer_count_last_in_tolerance_no_break(self) -> None:
        """firm = LARGEST n with P(overload) <= tol — NOT the first-overload break.

        Designed so a first-overload BREAK would give a DIFFERENT answer than
        last-in-tolerance. The P(overload) curve is engineered NON-MONOTONIC across
        the swept counts (a dip back into tolerance after a brief excursion):

          n=0 -> P=0.0   (<= 0.10, in tol)
          n=1 -> P=0.2   (>  0.10, OUT of tol)  <- a break would stop here, firm=0
          n=2 -> P=0.0   (<= 0.10, in tol)      <- last-in-tolerance keeps going
          n=3 -> P=0.4   (>  0.10, OUT of tol)

        last-in-tolerance => firm = 2 (the LARGEST n still <= tol).
        A first-overload break => firm = 0. The two disagree, pinning the semantics.
        """
        rating = _TR_RATING
        K = 5
        n_steps = 1
        ev_max = 3
        q_real = np.full((K, n_steps), rating, dtype="float64")  # loading exactly 1.0
        ev_pool = np.zeros((K, ev_max + 1, n_steps), dtype="float64")
        # n=0: no spike -> P=0.0
        # n=1: spike 1/5 realizations -> P=0.2
        ev_pool[:1, 1, 0] = 1.0
        # n=2: NO spike -> P=0.0 (dips back into tolerance)
        # n=3: spike 2/5 realizations -> P=0.4
        ev_pool[:2, 3, 0] = 1.0

        result = firm_transformer_count(q_real, ev_pool, rating, 0.10, ev_max)
        assert result["firm_ev_count"] == 2  # last-in-tolerance, NOT the break's 0
        np.testing.assert_allclose(result["p_overload_curve"], [0.0, 0.2, 0.0, 0.4])
        assert list(result["ev_sweep"]) == [0, 1, 2, 3]
        assert result["threshold_convention"] == "strict_gt_rating"

    def test_firm_transformer_count_return_contract(self) -> None:
        """firm_transformer_count returns the typed dict the stage consumes."""
        rating = _TR_RATING
        q_real = np.full((3, 1), rating * 0.5, dtype="float64")  # loading 0.5
        ev_pool = np.zeros((3, 3, 1), dtype="float64")  # ev_max = 2, no overload
        result = firm_transformer_count(q_real, ev_pool, rating, 0.10, 2)
        assert isinstance(result["firm_ev_count"], int)
        assert result["firm_ev_count"] == 2  # never overloads -> firm = ev_max
        assert all(isinstance(v, float) for v in result["p_overload_curve"])
        assert result["ev_sweep"] == [0, 1, 2]
        assert result["threshold_convention"] == "strict_gt_rating"
