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
    assert s["p_cong"] == pytest.approx(0.5)  # 110, 130 exceed 100
    assert s["peak_p50"] == pytest.approx(100.0)  # median of 50/90/110/130
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
    assert peaks.tolist() == [4.0]  # cold day 0's max
    peaks2 = _cold_day_peaks(load, np.array([False, True]), 4)
    assert peaks2.tolist() == [9.0]  # cold day 1's max
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
    ev_pools = [
        np.array([[0, 0, 20.0, 0, 0, 0, 20.0, 0], [0, 0, 20.0, 0, 0, 0, 20.0, 0]])
    ]  # (2, 8)
    cold = np.array([True, True])
    rating = 70.0
    # 0 EV, G=1: base peak 40 -> 57% -> no congestion
    s00 = _size_congestion(
        base_mc,
        ev_pools,
        cold,
        steps_per_day,
        homes=1,
        rating_kw=rating,
        g=1.0,
        ev_per_home=0.0,
    )
    assert s00["p_cong"] == 0.0
    # 2 EV/home, G=1: base 40 + 40 EV = 80 > 70 -> congested
    s2 = _size_congestion(
        base_mc,
        ev_pools,
        cold,
        steps_per_day,
        homes=1,
        rating_kw=rating,
        g=1.0,
        ev_per_home=2.0,
    )
    assert s2["p_cong"] == 1.0
    # growth raises the peak severity monotonically at fixed adoption
    lo = _size_congestion(
        base_mc,
        ev_pools,
        cold,
        steps_per_day,
        homes=1,
        rating_kw=rating,
        g=1.0,
        ev_per_home=1.0,
    )
    hi = _size_congestion(
        base_mc,
        ev_pools,
        cold,
        steps_per_day,
        homes=1,
        rating_kw=rating,
        g=1.2,
        ev_per_home=1.0,
    )
    assert hi["peak_max"] >= lo["peak_max"]


def test_interp_first_cross_hand_computed() -> None:
    """First crossing of an increasing curve, with the edge cases."""
    from projects.ev_hosting_flex.scripts.pipeline.analyze_congestion_risk import (
        _interp_first_cross,
    )

    xs = [0.0, 0.5, 1.0, 1.5]
    # rises 0 -> 0.08 -> 0.30 -> 0.60; crosses 0.10 between 0.5 and 1.0
    ys = [0.0, 0.08, 0.30, 0.60]
    assert _interp_first_cross(xs, ys, 0.10) == pytest.approx(0.545455, abs=1e-5)
    # already at/above the target at the first point -> the first x
    assert _interp_first_cross(xs, [0.2, 0.3, 0.4, 0.5], 0.10) == pytest.approx(0.0)
    # never reaches the target -> None
    assert _interp_first_cross(xs, [0.0, 0.01, 0.02, 0.03], 0.10) is None


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
    pcong = p["by_size"][feeder]["p_cong"]  # (G, ev)
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
    assert np.all(np.diff(n, axis=1) >= 0)  # rises with adoption (columns)
    # both first-risk triggers are reported (EV-axis and growth-axis); either
    # alone can trip the planning threshold
    assert p["first_risk_ev_per_home"] is not None
    # Re-based 2026-08-04 (latching thermostats): the growth-axis trigger is
    # FINITE again, and this is a qualitative flip worth stating.
    #
    # Under the 2026-08-01 re-base it was None: with the feeder judged against
    # the capability its own ambient allows, baseline electrification growth
    # alone never tripped the threshold. That conclusion rested on a base whose
    # dwellings never cycled — pre-diversified, so a 6-home aggregate came out
    # ~13% below measured. With per-zone latching thermostats the base carries
    # its real peaks and growth alone DOES trip the threshold, at g ~= 1.19.
    #
    # So K(T) does not, on its own, absorb baseline electrification growth. It
    # absorbed it only in company with a generator that under-peaked.
    assert p["first_risk_g"] is not None
    assert 1.0 < p["first_risk_g"] < 2.0, p["first_risk_g"]


@pytest.mark.skipif(not _REPORT.is_file(), reason=_SKIP)
def test_governed_congestion_report_contract() -> None:
    """The stage emits a canonical platform report with the summary keys."""
    from gridalyn.foundation.platform.reports import REQUIRED_REPORT_FIELDS

    report = json.loads(_REPORT.read_text())
    for field_name in REQUIRED_REPORT_FIELDS:
        assert field_name in report, f"missing report field {field_name}"
    for key in ("p_cong_g1_1ev", "peak_max_g1_1ev", "first_risk_ev_per_home"):
        assert key in report["summary"], sorted(report["summary"])


# ─── 4. The shared base-MC cache (syntgrid-lx7) ──────────────────────────
#
# Four stages share ``base_mc_by_size.npz`` under two K values. Keying it on the
# caller's ``k_base`` made every alternation a miss, so each of the four
# regenerated the whole set: 2.49 h of a measured 4.51 h run spent recomputing
# realizations that already existed. These tests pin the two properties that
# make the shared cache correct rather than merely faster.


def _stub_realizations(monkeypatch: pytest.MonkeyPatch) -> list[tuple[int, int]]:
    """Replace the expensive kernel with a cheap deterministic stand-in.

    A real realization costs ~62 s, so the seed bookkeeping — which is what
    these tests are actually about — is exercised against a stub that encodes
    its arguments instead.

    Args:
        monkeypatch: pytest fixture used to patch the kernel in place.

    Returns:
        A list that accumulates the ``(home_count, seed)`` of every call, so a
        test can assert both how many generations happened and with which
        seeds.
    """
    from projects.ev_hosting_flex.scripts.pipeline import analyze_congestion_risk as m

    calls: list[tuple[int, int]] = []

    def fake(temp: object, homes: int, seed: int, **kwargs: object) -> np.ndarray:
        calls.append((int(homes), int(seed)))
        return np.full(8, float(seed), dtype=float)

    monkeypatch.setattr(m, "annual_base_realization", fake)
    return calls


def test_smaller_k_is_a_bit_identical_prefix_of_the_larger(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A K=3 caller gets exactly the first three of the K=6 set.

    This is what makes serving both consumers from one file exact rather than
    approximate: the per-realization seed is a function of ``(homes, k)`` only,
    so realization k does not depend on how many were asked for.
    """
    from projects.ev_hosting_flex.scripts.pipeline import analyze_congestion_risk as m

    calls = _stub_realizations(monkeypatch)
    big = m._ensure_base_mc_cache(tmp_path, None, [4, 7], m._MAX_K_BASE)  # type: ignore[arg-type]
    generated = list(calls)

    calls.clear()
    small = m._ensure_base_mc_cache(tmp_path, None, [4, 7], 3)  # type: ignore[arg-type]

    assert calls == [], "the second caller regenerated instead of reading the cache"
    for homes in (4, 7):
        assert small[homes].shape[0] == 3
        np.testing.assert_array_equal(small[homes], big[homes][:3])
    # and the seeds really are index-derived, not a function of k_base
    assert generated == [
        (h, m.SEED + 100003 + h * 211 + k) for h in (4, 7) for k in range(m._MAX_K_BASE)
    ]


def test_alternating_k_no_longer_thrashes_the_cache(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The two K groups alternating must generate once in total, not once each.

    This is the regression under test: the flagship runs these four stages as
    6 -> 3 -> 6 -> 3, and every alternation used to be a full regeneration.
    """
    from projects.ev_hosting_flex.scripts.config import CONGESTION_K_BASE, TRIAGE_K_BASE
    from projects.ev_hosting_flex.scripts.pipeline import analyze_congestion_risk as m

    calls = _stub_realizations(monkeypatch)
    sizes = [2, 5]
    for k in (CONGESTION_K_BASE, TRIAGE_K_BASE, CONGESTION_K_BASE, TRIAGE_K_BASE):
        m._ensure_base_mc_cache(tmp_path, None, sizes, int(k))  # type: ignore[arg-type]

    # Derived from config, NOT from the module's own _MAX_K_BASE: against the
    # thrashing version this must fail on the COUNT (36 realizations for four
    # regenerations) rather than on a missing attribute.
    expected = len(sizes) * max(int(CONGESTION_K_BASE), int(TRIAGE_K_BASE))
    assert len(calls) == expected, (
        f"expected one generation of {expected} realizations, got {len(calls)} "
        f"— the cache is still thrashing between the two K groups"
    )


def test_a_new_home_count_regenerates_rather_than_returning_short(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cache that does not cover a requested size must not be served.

    ``sizes`` is deliberately not in the signature, so coverage is what guards
    this; without the check the caller would get a dict missing a key.
    """
    from projects.ev_hosting_flex.scripts.pipeline import analyze_congestion_risk as m

    calls = _stub_realizations(monkeypatch)
    m._ensure_base_mc_cache(tmp_path, None, [3], 3)  # type: ignore[arg-type]
    calls.clear()
    out = m._ensure_base_mc_cache(tmp_path, None, [3, 9], 3)  # type: ignore[arg-type]

    assert set(out) == {3, 9}
    assert calls, "a missing home-count was served from an incomplete cache"


def test_a_consumer_wanting_more_than_the_shared_maximum_is_refused(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Adding a consumer with a larger K must fail loudly, not silently truncate."""
    from projects.ev_hosting_flex.scripts.pipeline import analyze_congestion_risk as m

    _stub_realizations(monkeypatch)
    with pytest.raises(ValueError, match="exceeds the shared cache maximum"):
        m._ensure_base_mc_cache(tmp_path, None, [3], m._MAX_K_BASE + 1)  # type: ignore[arg-type]
