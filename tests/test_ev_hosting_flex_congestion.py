"""Unit + governed tests for the congestion-risk diagnostic stage.

Tiers: (1) hand-computed kernels, (2) a mini per-size assembly, (3) governed
reproduce-and-pin.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from projects.ev_hosting_flex.scripts._powerflow import (
    _cold_day_peaks,
    congestion_stats,
)


def test_congestion_stats_hand_computed() -> None:
    """Congestion probability + peak-severity tail (percentiles in % of rating)."""
    # peaks 50/90/110/130 kW on a 100 kW rating -> 50/90/110/130 %
    s = congestion_stats(np.array([50.0, 90.0, 110.0, 130.0]), 100.0)
    assert s["p_cong"] == pytest.approx(0.5)       # 110, 130 exceed 100
    assert s["peak_p50"] == pytest.approx(100.0)   # median of 50/90/110/130
    assert s["peak_max"] == pytest.approx(130.0)
    assert s["peak_p99"] >= s["peak_p95"] >= s["peak_p50"]
    # nothing over the rating -> zero probability
    s0 = congestion_stats(np.array([10.0, 20.0, 30.0]), 100.0)
    assert s0["p_cong"] == 0.0


def test_cold_day_peaks_hand_computed() -> None:
    """Daily coincident max over the cold days only."""
    # 2 days, 4 steps/day; day 0 cold, day 1 warm
    load = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 9.0, 6.0, 2.0])
    peaks = _cold_day_peaks(load, np.array([True, False]), 4)
    assert peaks.tolist() == [4.0]           # cold day 0's max
    peaks2 = _cold_day_peaks(load, np.array([False, True]), 4)
    assert peaks2.tolist() == [9.0]          # cold day 1's max
    both = _cold_day_peaks(load, np.array([True, True]), 4)
    assert both.tolist() == [4.0, 9.0]


def test_size_congestion_mini() -> None:
    """A mini per-size assembly: P(cong) rises with G and with EV adoption."""
    from projects.ev_hosting_flex.scripts.pipeline.analyze_congestion_risk import (
        _size_congestion,
    )

    steps_per_day = 4
    # 2 days both cold; one base realization for a 1-home size, peak 40 kW/day
    base_mc = np.array([[10.0, 20.0, 40.0, 5.0, 12.0, 22.0, 38.0, 6.0]])  # (1, 8)
    # one EV draw of 2 EVs, each adding a 20 kW spike at step 2 (the base peak hr)
    ev_pools = [np.array([[0, 0, 20.0, 0, 0, 0, 20.0, 0],
                          [0, 0, 20.0, 0, 0, 0, 20.0, 0]])]  # (2, 8)
    cold = np.array([True, True])
    rating = 70.0
    # 0 EV, G=1: base peak 40 -> 57% -> no congestion
    s00 = _size_congestion(base_mc, ev_pools, cold, steps_per_day, homes=1,
                           rating_kw=rating, g=1.0, ev_per_home=0.0)
    assert s00["p_cong"] == 0.0
    # 2 EV/home, G=1: base 40 + 40 EV = 80 > 70 -> congested
    s2 = _size_congestion(base_mc, ev_pools, cold, steps_per_day, homes=1,
                          rating_kw=rating, g=1.0, ev_per_home=2.0)
    assert s2["p_cong"] == 1.0
    # growth raises the peak severity monotonically at fixed adoption
    lo = _size_congestion(base_mc, ev_pools, cold, steps_per_day, homes=1,
                          rating_kw=rating, g=1.0, ev_per_home=1.0)
    hi = _size_congestion(base_mc, ev_pools, cold, steps_per_day, homes=1,
                          rating_kw=rating, g=1.2, ev_per_home=1.0)
    assert hi["peak_max"] >= lo["peak_max"]


# ─── 3. Governed reproduce-and-pin (skipif artifacts absent) ─────────────

from projects.ev_hosting_flex.scripts.config import PROJECT_OUTPUTS_DIR  # noqa: E402

_CONG = PROJECT_OUTPUTS_DIR / "json" / "congestion_risk.json"
_REPORT = PROJECT_OUTPUTS_DIR / "reports" / "congestion_risk_report.json"
_SKIP = (
    "congestion_risk.json not present; run analyze_congestion_risk.py first "
    "(outputs are gitignored)"
)


@pytest.mark.skipif(not _CONG.is_file(), reason=_SKIP)
def test_governed_congestion_risk() -> None:
    """Congestion risk rises with growth and adoption; peaks are heavy-tailed."""
    p = json.loads(_CONG.read_text())
    feeder = str(p["feeder_homes"])
    pcong = p["by_size"][feeder]["p_cong"]        # (G, ev)
    # P(cong) rises with EV adoption at every growth level, and with growth
    for row in pcong:
        assert row == sorted(row), f"P(cong) not rising with adoption: {row}"
    for ei in range(len(p["ev_per_home_grid"])):
        col = [pcong[gi][ei] for gi in range(len(p["g_grid"]))]
        assert col == sorted(col), f"P(cong) not rising with G at ev idx {ei}: {col}"
    # the reference feeder shows material congestion already at G=1, 1 EV/home,
    # with a heavy peak tail well over the rating
    assert p["reference_feeder"]["p_cong_g1_1ev"] > 0.0
    assert p["reference_feeder"]["peak_max_g1_1ev"] > 100.0
    # at-risk transformer count rises with growth; first-risk adoption is finite
    n = np.array(p["n_at_risk_by_scenario"])
    assert np.all(np.diff(n, axis=1) >= 0)        # rises with adoption (columns)
    assert p["first_risk_ev_per_home"] is not None


@pytest.mark.skipif(not _REPORT.is_file(), reason=_SKIP)
def test_governed_congestion_report_contract() -> None:
    """The stage emits a canonical platform report with the summary keys."""
    from gridalyn.foundation.platform.reports import REQUIRED_REPORT_FIELDS

    report = json.loads(_REPORT.read_text())
    for field_name in REQUIRED_REPORT_FIELDS:
        assert field_name in report, f"missing report field {field_name}"
    for key in ("p_cong_g1_1ev", "peak_max_g1_1ev", "first_risk_ev_per_home"):
        assert key in report["summary"], sorted(report["summary"])
