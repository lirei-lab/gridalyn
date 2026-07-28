"""Unit + governed tests for the cold-tail insurance study."""

from __future__ import annotations

import json

import numpy as np
import pytest


def test_realization_insurance_shapes_and_shortfall() -> None:
    """Per realization: firm is an int, the sweep arrays match the grid, and
    shortfall is exactly (firm < adoption)."""
    from projects.ev_hosting_flex.scripts.pipeline.analyze_cold_insurance import (
        realization_insurance,
    )

    horizon = 365 * 96
    tday = np.full(365, -5.0)
    base = np.full(horizon, 40.0)          # 40 kW feeder base
    pool = np.zeros((12, horizon))
    pool[:, ::96] = 6.0                     # one daily EV spike per EV
    grid = [1, 2, 4, 8]
    out = realization_insurance(
        base, pool, tday, 71.25, 15, 0, grid, [71.25, 95.0]
    )
    assert isinstance(out["firm"], int) and out["firm"] >= 0
    assert len(out["shortfall"]) == len(grid)
    assert len(out["covered"]) == len(grid)
    assert len(out["curtailed_kwh"]) == len(grid)
    assert len(out["firm_by_rung"]) == 2
    for i, a in enumerate(grid):
        assert out["shortfall"][i] == (out["firm"] < a)
    assert all(c >= 0.0 for c in out["curtailed_kwh"])


def test_aggregate_insurance_risk_curve_and_costs() -> None:
    """The risk curve is non-decreasing in adoption, coverage and residual risk
    sum to 1, flex viability is exactly coverage >= target, and the reinforcement
    ladder / headline definitions behave as specified."""
    from projects.ev_hosting_flex.scripts.pipeline.analyze_cold_insurance import (
        aggregate_insurance,
    )

    grid = [1, 2, 3]
    # three realizations with firm 1, 2, 3 -> P(firm<A) rises with A.
    # firm_by_rung: index 0 is the PRESENT rung (75 kVA), index 1 an upgrade.
    rows = [
        {"firm": 1, "firm_by_rung": [1, 3], "shortfall": [False, True, True],
         "covered": [True, True, False], "curtailed_kwh": [0.0, 10.0, 40.0],
         "curtailed_frac": [0.0, 0.02, 0.20]},
        {"firm": 2, "firm_by_rung": [2, 3], "shortfall": [False, False, True],
         "covered": [True, True, True], "curtailed_kwh": [0.0, 0.0, 20.0],
         "curtailed_frac": [0.0, 0.0, 0.05]},
        {"firm": 3, "firm_by_rung": [3, 3], "shortfall": [False, False, False],
         "covered": [True, True, True], "curtailed_kwh": [0.0, 0.0, 0.0],
         "curtailed_frac": [0.0, 0.0, 0.0]},
    ]
    agg = aggregate_insurance(rows, grid, [75.0, 100.0], 0.95, 0.065)
    risk = agg["activation_frequency_by_adoption"]
    assert risk == sorted(risk), risk                       # non-decreasing
    for i in range(len(grid)):
        cov = agg["coverage_by_adoption"][i]
        assert abs(cov + agg["residual_risk_by_adoption"][i] - 1.0) < 1e-9
        assert agg["flex_viable_by_adoption"][i] == (cov >= 0.95)
        assert agg["expected_cost_flex_by_adoption"][i] >= 0.0

    # Reinforcement ladder: at A=1 every realization already reaches firm>=1 on the
    # PRESENT rung -> nothing to buy; at A=2,3 the present rung misses the 95 %
    # target so the upgrade rung is chosen and costs money.
    assert agg["kva_required_by_adoption"][0] == 75.0
    assert agg["expected_cost_reinforce_by_adoption"][0] == 0.0
    assert agg["kva_required_by_adoption"][1] == 100.0
    assert agg["expected_cost_reinforce_by_adoption"][1] > 0.0

    # Headlines: the viability limit is the first adoption whose coverage falls
    # below the target (A=3 here, coverage 2/3).
    assert agg["flex_viability_limit_adoption"] == 3
    # The crossover only considers adoptions that need reinforcement AND where
    # flexibility is still viable; it is None when flexibility never costs more.
    co = agg["crossover_adoption"]
    assert co is None or co in grid

    # Denied charging is priced and reported separately so the concession is visible.
    assert all(v >= 0.0 for v in agg["unserved_value_by_adoption"])
    assert len(agg["mean_curtailed_frac_by_adoption"]) == len(grid)


# ─── Governed reproduce-and-pin (skipif artifacts absent) ─────────────
from projects.ev_hosting_flex.scripts.config import PROJECT_OUTPUTS_DIR  # noqa: E402

_INS = PROJECT_OUTPUTS_DIR / "json" / "cold_insurance.json"
_CRED = PROJECT_OUTPUTS_DIR / "json" / "credibility.json"
_REPORT = PROJECT_OUTPUTS_DIR / "reports" / "cold_insurance_report.json"
_SKIP = "cold_insurance.json absent; run analyze_cold_insurance.py first (gitignored)"


@pytest.mark.skipif(not _INS.is_file(), reason=_SKIP)
def test_governed_firm_distribution_matches_credibility() -> None:
    """CONSISTENCY GUARD: this study and analyze_credibility share seeds, so they
    must report the SAME firm distribution. Two studies in one project cannot
    disagree about the hosting capacity."""
    ins = json.loads(_INS.read_text())
    if not _CRED.is_file():
        pytest.skip("credibility.json absent")
    cred = json.loads(_CRED.read_text())
    assert sorted(ins["firm_samples"]) == sorted(
        int(v) for v in cred["samples"]["firm"]
    )


@pytest.mark.skipif(not _INS.is_file(), reason=_SKIP)
def test_governed_cold_insurance() -> None:
    """Risk curve rises with adoption; coverage and residual risk are consistent;
    the flexibility cost grows with the number of contracted EVs."""
    p = json.loads(_INS.read_text())
    risk = p["activation_frequency_by_adoption"]
    assert risk == sorted(risk), risk
    target = float(p["reliability_target"])
    for i in range(len(p["adoption_grid"])):
        cov = p["coverage_by_adoption"][i]
        assert abs(cov + p["residual_risk_by_adoption"][i] - 1.0) < 1e-6
        assert p["flex_viable_by_adoption"][i] == (cov >= target)
    cf = p["expected_cost_flex_by_adoption"]
    assert cf == sorted(cf), "flex cost must grow with contracted EVs"
    assert p["firm_p05"] <= p["firm_p50"] <= p["firm_p95"]


@pytest.mark.skipif(not _REPORT.is_file(), reason=_SKIP)
def test_governed_cold_insurance_report_contract() -> None:
    """The stage emits a canonical platform report with the summary keys."""
    from gridalyn.foundation.platform.reports import REQUIRED_REPORT_FIELDS

    report = json.loads(_REPORT.read_text())
    for field_name in REQUIRED_REPORT_FIELDS:
        assert field_name in report, f"missing {field_name}"
    for key in ("p_short_at_ref", "coverage_at_ref", "crossover_adoption",
                "short_years_if_plan_p50"):
        assert key in report["summary"], sorted(report["summary"])
