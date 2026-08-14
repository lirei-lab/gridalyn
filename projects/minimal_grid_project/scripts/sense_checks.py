"""Objective sense checks for the ``minimal_grid_project`` study.

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
    report = report_summary(project, "outputs/reports/minimal_grid_report.json")
    buses = read_csv(project, "outputs/data/buses.csv")
    lines = read_csv(project, "outputs/data/lines.csv")
    loads = read_csv(project, "outputs/data/loads.csv")
    record_check(
        checks,
        "minimal_intent_is_explicit",
        report.get("project_intent") == "minimal_grid_hello_world",
        report.get("project_intent"),
        "minimal_grid_hello_world",
    )
    record_check(
        checks,
        "minimal_bus_count",
        report.get("bus_count") == 5 and len(buses) == 5,
        {"report": report.get("bus_count"), "csv": len(buses)},
        5,
    )
    record_check(
        checks,
        "minimal_line_count",
        report.get("line_count") == 4 and len(lines) == 4,
        {"report": report.get("line_count"), "csv": len(lines)},
        4,
    )
    record_check(
        checks,
        "minimal_load_count",
        report.get("load_count") == 4 and len(loads) == 4,
        {"report": report.get("load_count"), "csv": len(loads)},
        4,
    )
    record_check(
        checks,
        "minimal_powerflow_converges",
        report.get("powerflow_converged") is True,
        report.get("powerflow_converged"),
        True,
    )
    record_check(
        checks,
        "minimal_voltage_is_near_nominal",
        between(report.get("min_voltage_pu"), 0.98, 1.02),
        report.get("min_voltage_pu"),
        "0.98 <= min_voltage_pu <= 1.02",
    )
    record_check(
        checks,
        "minimal_not_overloaded",
        float(report.get("max_line_loading_pct", 999)) < 20.0,
        report.get("max_line_loading_pct"),
        "< 20%",
    )
    record_check(
        checks,
        "minimal_has_positive_load",
        float(report.get("total_load_mw", 0)) > 0,
        report.get("total_load_mw"),
        "> 0 MW",
    )
