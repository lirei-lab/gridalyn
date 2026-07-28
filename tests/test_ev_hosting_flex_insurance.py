"""Unit + governed tests for the cold-tail insurance study."""

from __future__ import annotations

import json  # noqa: F401  (governed reproduce-and-pin tests)

import numpy as np
import pytest  # noqa: F401  (governed reproduce-and-pin tests)


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
    sum to 1, and flex viability is exactly coverage >= target."""
    from projects.ev_hosting_flex.scripts.pipeline.analyze_cold_insurance import (
        aggregate_insurance,
    )

    grid = [1, 2, 3]
    # three realizations with firm 1, 2, 3 -> P(firm<A) rises with A
    rows = [
        {"firm": 1, "firm_by_rung": [1, 3], "shortfall": [False, True, True],
         "covered": [True, True, False], "curtailed_kwh": [0.0, 10.0, 40.0]},
        {"firm": 2, "firm_by_rung": [2, 3], "shortfall": [False, False, True],
         "covered": [True, True, True], "curtailed_kwh": [0.0, 0.0, 20.0]},
        {"firm": 3, "firm_by_rung": [3, 3], "shortfall": [False, False, False],
         "covered": [True, True, True], "curtailed_kwh": [0.0, 0.0, 0.0]},
    ]
    agg = aggregate_insurance(rows, grid, [75.0, 100.0], 0.95, 0.065)
    risk = agg["activation_frequency_by_adoption"]
    assert risk == sorted(risk), risk                       # non-decreasing
    for i in range(len(grid)):
        cov = agg["coverage_by_adoption"][i]
        assert abs(cov + agg["residual_risk_by_adoption"][i] - 1.0) < 1e-9
        assert agg["flex_viable_by_adoption"][i] == (cov >= 0.95)
        assert agg["expected_cost_flex_by_adoption"][i] >= 0.0
