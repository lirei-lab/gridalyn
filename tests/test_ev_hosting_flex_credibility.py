"""Unit + governed tests for the credibility (confidence-interval) stage."""

from __future__ import annotations

import json

import numpy as np
import pytest


def test_winter_offsets_deterministic_and_anchored() -> None:
    """delta_0 = 0 (the nominal anchor); same seed -> same offsets."""
    from projects.ev_hosting_flex.scripts.pipeline.analyze_credibility import (
        winter_offsets,
    )

    a = winter_offsets(10, 1.5, 123)
    b = winter_offsets(10, 1.5, 123)
    assert a[0] == 0.0                         # realization 0 = nominal weather
    assert np.array_equal(a, b)                # deterministic
    assert len(a) == 10
    assert abs(float(np.std(a[1:]))) > 0.0     # the rest vary


def test_realization_headlines_types_and_cold_monotone() -> None:
    """firm/flex/breakeven are non-negative ints; a colder base does not raise
    firm (more load -> no more hosting)."""
    from projects.ev_hosting_flex.scripts.pipeline.analyze_credibility import (
        realization_headlines,
    )

    tday = np.full(365, -5.0)
    horizon = 365 * 96
    base = np.full(horizon, 40.0)          # 40 kW feeder base
    colder = np.full(horizon, 55.0)        # a colder year -> higher base
    pool = np.zeros((12, horizon))
    pool[:, ::96] = 6.0                     # a daily EV spike
    warm = realization_headlines(base, pool, tday, 71.25, 15, 0)
    cold = realization_headlines(colder, pool, tday, 71.25, 15, 0)
    for k in ("firm", "flex", "breakeven"):
        assert isinstance(warm[k], int) and warm[k] >= 0
    assert cold["firm"] <= warm["firm"]     # colder -> not more firm hosting


def test_stats_ordering_and_p_at_point() -> None:
    """P5 <= P50 <= P95 and p_at_point in [0, 1]."""
    from projects.ev_hosting_flex.scripts.pipeline.analyze_credibility import _stats

    st = _stats([2.0, 3.0, 3.0, 4.0, 3.0, 5.0], point=3.0)
    assert st["p05"] <= st["p50"] <= st["p95"]
    assert 0.0 <= st["p_at_point"] <= 1.0
    assert st["mode"] == 3.0


# ─── Governed reproduce-and-pin (skipif artifacts absent) ─────────────
from projects.ev_hosting_flex.scripts.config import PROJECT_OUTPUTS_DIR  # noqa: E402

_CRED = PROJECT_OUTPUTS_DIR / "json" / "credibility.json"
_REPORT = PROJECT_OUTPUTS_DIR / "reports" / "credibility_report.json"
_FIRM = PROJECT_OUTPUTS_DIR / "json" / "firm_hosting_annual.json"
_CURT = PROJECT_OUTPUTS_DIR / "json" / "curtailment_hosting.json"
_ECON = PROJECT_OUTPUTS_DIR / "json" / "curtailment_economics.json"
_SKIP = "credibility.json absent; run analyze_credibility.py first (gitignored)"


@pytest.mark.skipif(not _CRED.is_file(), reason=_SKIP)
def test_governed_credibility() -> None:
    """P5<=P50<=P95 for firm/flex/breakeven; realization 0 reproduces the governed
    firm/flex/breakeven points (the consistency guard against replication drift)."""
    p = json.loads(_CRED.read_text())
    for key in ("firm", "flex", "breakeven"):
        assert p[key]["p05"] <= p[key]["p50"] <= p[key]["p95"], key
    r0 = p["point_realization_0"]
    if _FIRM.is_file():
        assert int(r0["firm"]) == int(json.loads(_FIRM.read_text())["firm_ev_count"])
    if _CURT.is_file():
        assert int(r0["flex"]) == int(
            json.loads(_CURT.read_text())["flexible_ev_count"]
        )
    if _ECON.is_file():
        assert int(r0["breakeven"]) == int(
            json.loads(_ECON.read_text())["breakeven_ev_count"]
        )


@pytest.mark.skipif(not _REPORT.is_file(), reason=_SKIP)
def test_governed_credibility_report_contract() -> None:
    """The stage emits a canonical platform report with the summary keys."""
    from gridalyn.foundation.platform.reports import REQUIRED_REPORT_FIELDS

    report = json.loads(_REPORT.read_text())
    for field_name in REQUIRED_REPORT_FIELDS:
        assert field_name in report, f"missing {field_name}"
    for key in ("firm_p50", "flex_p50", "breakeven_p50", "base_peak_p50"):
        assert key in report["summary"], sorted(report["summary"])
