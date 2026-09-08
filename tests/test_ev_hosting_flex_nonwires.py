"""Unit + governed tests for the pilar-2 network non-wires value stage."""

from __future__ import annotations

import json

import numpy as np
import pytest

from projects.ev_hosting_flex.scripts._powerflow import flex_deferral_curves


def test_flex_deferral_curves_shapes_and_monotone() -> None:
    """peak_noflex rises with adoption; curtailed_frac is 0 until the flexed
    peak binds, then rises; the flex caps the no-flex overload."""
    # a flat 6 kW/home base with a 5 kW/home evening EV spike, 6 homes, 50 kW rating
    base = np.full(24, 6.0)
    ev = np.zeros(24)
    ev[18:22] = 5.0  # per-EV evening kW
    grid = np.array([0.0, 0.5, 1.0, 1.5, 2.0])
    out = flex_deferral_curves(base, ev, 6, 50.0, grid)
    assert out["peak_noflex"].shape == (5,)
    assert list(out["peak_noflex"]) == sorted(out["peak_noflex"])  # rises
    assert out["curtailed_frac"][0] == 0.0  # no EV -> none
    assert out["curtailed_frac"][-1] >= out["curtailed_frac"][0]  # rises
    assert (out["curtailed_frac"] >= 0.0).all()


def test_ramp_monotone_and_invertible() -> None:
    """The logistic ramp rises 0->max and year_at is its inverse."""
    from projects.ev_hosting_flex.scripts._annual import (
        adoption_at_year,
        year_at_adoption,
    )
    from projects.ev_hosting_flex.scripts.config import RAMP_MAX_EV_PER_HOME

    ys = np.linspace(0, 15, 16)
    ad = np.array([adoption_at_year(float(y)) for y in ys])
    assert list(ad) == sorted(ad)  # non-decreasing
    assert ad[0] < ad[-1] <= RAMP_MAX_EV_PER_HOME + 1e-9
    # invertible on the interior
    for y in (2.0, 5.0, 9.0, 12.0):
        assert year_at_adoption(adoption_at_year(y)) == pytest.approx(y, abs=1e-6)
    # boundary: adoption >= max -> +inf (never reached); <= 0 -> year 0
    assert year_at_adoption(RAMP_MAX_EV_PER_HOME) == float("inf")
    assert year_at_adoption(0.0) == 0.0


def test_size_deferral_nonnegative_and_zero_when_no_defer() -> None:
    """defer_npv >= 0 when A1 > A0; = 0 when the flex defers nothing (A1 = A0)."""
    from projects.ev_hosting_flex.scripts.pipeline.analyze_nonwires_value import (
        _size_deferral,
    )

    grid = [0.0, 0.5, 1.0, 1.5, 2.0]
    # peak crosses 100 at ~0.5; curtailment stays tiny -> A1 well past A0
    curves = {
        "peak_noflex": np.array([60.0, 100.0, 140.0, 180.0, 220.0]),
        "curtailed_frac": np.array([0.0, 0.0, 0.02, 0.05, 0.09]),
        "curtailed_kwh": np.array([0.0, 0.0, 5.0, 12.0, 20.0]),
    }
    d = _size_deferral(curves, grid, 6, capex=3000.0, crf=0.065, n_cold_days=163)
    assert d["defer_npv"] >= 0.0
    assert d["a1"] is None or d["a1"] >= d["a0"]
    # no-overload size -> zero deferral
    flat = {
        "peak_noflex": np.array([40.0, 50.0, 60.0, 70.0, 80.0]),
        "curtailed_frac": np.zeros(5),
        "curtailed_kwh": np.zeros(5),
    }
    z = _size_deferral(flat, grid, 6, capex=3000.0, crf=0.065, n_cold_days=163)
    assert z["defer_npv"] == 0.0


def _substation(a0: float | None) -> dict:  # type: ignore[type-arg]
    from projects.ev_hosting_flex.scripts.pipeline.analyze_nonwires_value import (
        _substation_deferral_at,
    )

    return _substation_deferral_at(a0, n_tx=2, mva=25.0)


def test_substation_deferral_is_zero_when_the_firm_crossing_is_beyond_the_horizon() -> (
    None
):
    """A0 reached only after the planning horizon defers nothing -- and never
    goes NEGATIVE.

    The regression: only the deferred crossing (y1) was capped at the horizon,
    so a0 just short of saturation gave y0 = 15.885 against a 15-year horizon
    and defer_npv = capex * ((1+r)^-15.885 - (1+r)^-15) < 0, with trafo_years
    = 15 - 15.885 = -0.885. The clean run of 2026-09-04 hit exactly this at
    a0 = 1.313696 and flipped the study's total deferral NPV negative.
    """
    from projects.ev_hosting_flex.scripts._annual import year_at_adoption
    from projects.ev_hosting_flex.scripts.config import RAMP_HORIZON_YEARS

    a0 = 1.313696  # the clean run's substation N-1 crossing, EV/home
    y0 = year_at_adoption(a0)
    assert np.isfinite(y0) and y0 > float(RAMP_HORIZON_YEARS), (
        "precondition: this a0 must be reachable but after the horizon, or the "
        "test no longer exercises the defect"
    )
    d = _substation(a0)
    assert d["defer_npv"] == 0.0
    assert d["trafo_years"] == 0.0
    assert d["needed_within_horizon"] is False
    assert d["a1"] == pytest.approx(a0 * 1.5)


class _StubScript:
    """Just enough ProjectScript for _substation_deferral: one JSON to read."""

    def __init__(self, a0: float) -> None:
        self._sub = {
            "n1_reinforcement_penetration_emergency": a0,
            "n_transformers": 2,
            "mva_per_transformer": 25.0,
        }

    def read_json(self, relative: str) -> dict:  # type: ignore[type-arg]
        assert relative == "outputs/json/network_characterization.json"
        return {"substation": self._sub}


def test_substation_deferral_never_negative_through_the_stage_interface() -> None:
    """The regression guard, through the interface the stage actually calls.

    Deliberately NOT through the pure helper: against the previous code this
    must fail on the VALUE (-25413.63 and -0.885 years at the clean run's a0),
    not on a missing symbol.
    """
    from projects.ev_hosting_flex.scripts.pipeline.analyze_nonwires_value import (
        _substation_deferral,
    )

    d = _substation_deferral(_StubScript(1.313696), sizing={}, crf=0.065)  # type: ignore[arg-type]
    assert d["defer_npv"] >= 0.0, f"substation deferral went negative: {d}"
    assert d["trafo_years"] >= 0.0, f"substation deferred years went negative: {d}"
    assert d["defer_npv"] == 0.0 and d["trafo_years"] == 0.0


def test_substation_deferral_is_zero_when_never_crossed() -> None:
    """A0 = None (never crosses) and A0 past saturation (unreachable) both defer 0."""
    from projects.ev_hosting_flex.scripts._annual import year_at_adoption

    assert _substation(None)["defer_npv"] == 0.0
    unreachable = 1.341342  # the collage's a0, past the 1.32 saturation ramp
    assert not np.isfinite(year_at_adoption(unreachable))
    d = _substation(unreachable)
    assert d["defer_npv"] == 0.0 and d["trafo_years"] == 0.0
    assert d["needed_within_horizon"] is False


def test_substation_deferral_is_positive_and_capped_inside_the_horizon() -> None:
    """A0 inside the horizon: value > 0, years > 0, and never past the horizon."""
    from projects.ev_hosting_flex.scripts._annual import year_at_adoption
    from projects.ev_hosting_flex.scripts.config import RAMP_HORIZON_YEARS

    a0 = 1.0
    y0 = year_at_adoption(a0)
    assert 0.0 < y0 < float(RAMP_HORIZON_YEARS)
    d = _substation(a0)
    assert d["needed_within_horizon"] is True
    assert d["defer_npv"] > 0.0
    assert d["trafo_years"] > 0.0
    assert d["trafo_years"] <= float(RAMP_HORIZON_YEARS) - y0 + 1e-9
    # a1 = 1.5 EV/home is past saturation -> avoided within the horizon, capped
    assert d["avoided_beyond_horizon"] is True
    assert d["trafo_years"] == pytest.approx(float(RAMP_HORIZON_YEARS) - y0, abs=1e-6)


# ─── Governed reproduce-and-pin (skipif artifacts absent) ─────────────
from projects.ev_hosting_flex.scripts.config import PROJECT_OUTPUTS_DIR  # noqa: E402

_NW = PROJECT_OUTPUTS_DIR / "json" / "nonwires_value.json"
_REPORT = PROJECT_OUTPUTS_DIR / "reports" / "nonwires_value_report.json"
_SKIP = "nonwires_value.json absent; run analyze_nonwires_value.py first (gitignored)"


@pytest.mark.skipif(not _NW.is_file(), reason=_SKIP)
def test_governed_nonwires_value() -> None:
    """Network deferral is positive; the snapshot is non-negative; something defers."""
    p = json.loads(_NW.read_text())
    assert p["total_deferral_npv"] > 0.0
    assert p["total_trafo_years_deferred"] > 0.0
    assert all(x >= 0.0 for x in p["snapshot_capex_deferred"])
    assert any(
        (s["a0"] is not None and s["a1"] is not None and s["a1"] > s["a0"])
        for s in p["by_size"].values()
    )


@pytest.mark.skipif(not _REPORT.is_file(), reason=_SKIP)
def test_governed_nonwires_report_contract() -> None:
    """The stage emits a canonical platform report with the summary keys."""
    from gridalyn.foundation.platform.reports import REQUIRED_REPORT_FIELDS

    report = json.loads(_REPORT.read_text())
    for field_name in REQUIRED_REPORT_FIELDS:
        assert field_name in report, f"missing {field_name}"
    for key in (
        "total_deferral_npv",
        "total_trafo_years_deferred",
        "first_reinforcement_year",
    ):
        assert key in report["summary"], sorted(report["summary"])
