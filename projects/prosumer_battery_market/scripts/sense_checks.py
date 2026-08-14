"""Objective sense checks for the ``prosumer_battery_market`` study.

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
    read_csv,
    record_check,
    report_summary,
)


def check(project: StudyProject, checks: CheckList) -> None:
    feeder = report_summary(project, "outputs/reports/synthetic_feeder_report.json")
    market = report_summary(
        project, "outputs/reports/prosumer_realtime_market_report.json"
    )
    dispatch = read_csv(project, "outputs/operations/battery_dispatch.csv")
    prosumers = read_csv(project, "outputs/data/prosumers.csv")
    record_check(
        checks,
        "prosumer_feeder_converges",
        feeder.get("converged") is True,
        feeder.get("converged"),
        True,
    )
    record_check(
        checks,
        "prosumer_count_positive",
        int(market.get("prosumer_count", 0)) > 0
        and len(prosumers) == int(market.get("prosumer_count", 0)),
        {"report": market.get("prosumer_count"), "csv": len(prosumers)},
        "> 0 and consistent",
    )
    horizon = int(market.get("forecast_horizon_intervals", 0))
    intervals = int(market.get("interval_count", 0))
    record_check(
        checks,
        "prosumer_horizon_tiles_intervals",
        horizon > 0 and intervals % horizon == 0,
        {"horizon": horizon, "intervals": intervals},
        "rolling horizon divides interval count",
    )
    record_check(
        checks,
        "prosumer_cleared_not_above_required",
        float(market.get("total_cleared_mwh", 0))
        <= float(market.get("total_required_mwh", 0)) + 1e-9,
        market.get("total_cleared_mwh"),
        "<= total_required_mwh",
    )
    record_check(
        checks,
        "prosumer_peak_import_not_increased",
        float(market.get("peak_import_after_mw", 999))
        <= float(market.get("peak_import_before_mw", 0)) + 1e-9,
        market.get("peak_import_after_mw"),
        "<= before",
    )
    record_check(
        checks,
        "prosumer_voltage_after_safe",
        float(market.get("min_voltage_after_pu", 0)) >= 0.95,
        market.get("min_voltage_after_pu"),
        ">= 0.95",
    )
    record_check(
        checks,
        "prosumer_line_loading_after_safe",
        float(market.get("max_line_loading_after_percent", 999)) < 100.0,
        market.get("max_line_loading_after_percent"),
        "< 100%",
    )
    record_check(
        checks,
        "prosumer_dispatch_non_negative",
        (dispatch["dispatch_mwh"] >= -1e-9).all(),
        float(dispatch["dispatch_mwh"].min()),
        ">= 0",
    )
