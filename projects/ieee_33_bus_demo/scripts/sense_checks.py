"""Objective sense checks for the ``ieee_33_bus_demo`` study.

Moved out of ``gridalyn/projects/sense_checks.py`` on 2026-08-14. These
assertions are study knowledge -- which artifacts this objective produces and
what plausible values look like for it -- so they belong beside the study.
Declared in ``project.yaml`` under ``spec.validation.senseChecker``; the
library discovers them there and knows nothing about this study by name.
"""

from __future__ import annotations

from gridalyn.projects.models import StudyProject
from gridalyn.projects.sense_check_api import (
    CheckList,
    between,
    read_csv,
    record_check,
    report_summary,
)


def check(project: StudyProject, checks: CheckList) -> None:
    base = report_summary(project, "outputs/reports/ieee33_powerflow_report.json")
    scenario = report_summary(
        project, "outputs/reports/ieee33_scenario_comparison_report.json"
    )
    results = read_csv(project, "outputs/data/scenario_results.csv").set_index(
        "scenario_id"
    )
    expected_ids = {
        "baseline",
        "load_growth_20",
        "pv_midday",
        "ev_evening_peak",
        "pv_plus_ev",
    }
    record_check(
        checks,
        "ieee33_bus_count",
        base.get("bus_count") == 33,
        base.get("bus_count"),
        33,
    )
    record_check(
        checks,
        "ieee33_line_count",
        base.get("line_count") == 37,
        base.get("line_count"),
        "37 pandapower case33bw branches",
    )
    record_check(
        checks,
        "ieee33_single_slack",
        base.get("slack_count") == 1,
        base.get("slack_count"),
        1,
    )
    record_check(
        checks,
        "ieee33_baseline_converges",
        base.get("converged") is True,
        base.get("converged"),
        True,
    )
    record_check(
        checks,
        "ieee33_has_expected_scenarios",
        set(scenario.get("scenario_ids", [])) == expected_ids,
        scenario.get("scenario_ids"),
        sorted(expected_ids),
    )
    record_check(
        checks,
        "ieee33_scenario_count",
        scenario.get("scenario_count") == 5,
        scenario.get("scenario_count"),
        5,
    )
    record_check(
        checks,
        "ieee33_load_growth_worsens_voltage",
        results.loc["load_growth_20", "min_voltage_pu"]
        <= results.loc["baseline", "min_voltage_pu"],
        float(results.loc["load_growth_20", "min_voltage_pu"]),
        "<= baseline",
    )
    record_check(
        checks,
        "ieee33_ev_peak_increases_net_demand",
        results.loc["ev_evening_peak", "net_demand_mw"]
        > results.loc["baseline", "net_demand_mw"],
        float(results.loc["ev_evening_peak", "net_demand_mw"]),
        "> baseline",
    )
    record_check(
        checks,
        "ieee33_pv_reduces_net_demand",
        results.loc["pv_midday", "net_demand_mw"]
        < results.loc["baseline", "net_demand_mw"],
        float(results.loc["pv_midday", "net_demand_mw"]),
        "< baseline",
    )
    record_check(
        checks,
        "ieee33_voltage_range_plausible",
        between(scenario.get("min_voltage_pu"), 0.85, 1.08),
        scenario.get("min_voltage_pu"),
        "0.85 <= min_voltage_pu <= 1.08",
    )
