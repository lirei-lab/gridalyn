"""Objective sense checks for the ``synthetic_geojson_feeder`` study.

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
    read_json_report,
    record_check,
    report_summary,
)


def check(project: StudyProject, checks: CheckList) -> None:
    footprint = report_summary(
        project, "outputs/reports/building_footprints_report.json"
    )
    report = report_summary(
        project, "outputs/reports/synthetic_geojson_feeder_report.json"
    )
    validation = read_json_report(
        project, "outputs/reports/synthetic_network_validation_report.json"
    )
    buses = read_csv(project, "outputs/data/buses.csv")
    lines = read_csv(project, "outputs/data/lines.csv")
    loads = read_csv(project, "outputs/data/loads.csv")
    record_check(
        checks,
        "geojson_building_count",
        footprint.get("building_count") == 9 and report.get("building_count") == 9,
        {
            "input": footprint.get("building_count"),
            "network": report.get("building_count"),
        },
        9,
    )
    record_check(
        checks,
        "geojson_loads_match_buildings",
        report.get("pandapower_load_count")
        == report.get("building_count")
        == len(loads),
        {"report_loads": report.get("pandapower_load_count"), "csv_loads": len(loads)},
        "one load per building",
    )
    record_check(
        checks,
        "geojson_network_has_transformers",
        int(report.get("pandapower_transformer_count", 0)) >= 1,
        report.get("pandapower_transformer_count"),
        ">= 1",
    )
    record_check(
        checks,
        "geojson_powerflow_converges",
        report.get("powerflow_converged") is True,
        report.get("powerflow_converged"),
        True,
    )
    record_check(
        checks,
        "geojson_validation_report_valid",
        validation.get("valid") is True,
        validation.get("valid"),
        True,
    )
    record_check(
        checks,
        "geojson_no_isolated_nodes",
        validation.get("topology", {}).get("isolated_nodes_total") == 0,
        validation.get("topology", {}).get("isolated_nodes_total"),
        0,
    )
    record_check(
        checks,
        "geojson_voltage_plausible",
        between(report.get("min_voltage_pu"), 0.90, 1.05),
        report.get("min_voltage_pu"),
        "0.90 <= min_voltage_pu <= 1.05",
    )
    record_check(
        checks,
        "geojson_tables_non_empty",
        not buses.empty and not lines.empty and not loads.empty,
        {"buses": len(buses), "lines": len(lines), "loads": len(loads)},
        "non-empty tables",
    )
