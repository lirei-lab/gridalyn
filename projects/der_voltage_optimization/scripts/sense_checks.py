"""Objective sense checks for the ``der_voltage_optimization`` study.

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
    feeder = report_summary(project, "outputs/reports/der_feeder_report.json")
    opt = report_summary(
        project, "outputs/reports/der_voltage_optimization_report.json"
    )
    dispatch = read_csv(project, "outputs/operations/der_dispatch.csv")
    record_check(
        checks,
        "der_feeder_converges",
        feeder.get("converged") is True,
        feeder.get("converged"),
        True,
    )
    record_check(
        checks,
        "der_solver_optimal",
        opt.get("solver_status") in {"optimal", "optimal_inaccurate"},
        opt.get("solver_status"),
        "optimal or optimal_inaccurate",
    )
    available = float(opt.get("total_pv_available_mw", 0))
    accounted = float(opt.get("total_pv_dispatch_mw", 0)) + float(
        opt.get("total_pv_curtailment_mw", 0)
    )
    record_check(
        checks,
        "der_energy_accounting_balances",
        abs(accounted - available) <= 1e-5,
        {"available": available, "dispatch_plus_curtailment": accounted},
        "dispatch + curtailment ~= available",
    )
    record_check(
        checks,
        "der_max_voltage_reduced",
        float(opt.get("verified_max_voltage_after_pu", 9))
        <= float(opt.get("verified_max_voltage_before_pu", 0)) + 1e-9,
        opt.get("verified_max_voltage_after_pu"),
        "<= before",
    )
    record_check(
        checks,
        "der_voltage_upper_limit_met",
        float(opt.get("verified_max_voltage_after_pu", 9)) <= 1.05 + 1e-6,
        opt.get("verified_max_voltage_after_pu"),
        "<= 1.05",
    )
    record_check(
        checks,
        "der_voltage_lower_limit_met",
        float(opt.get("verified_min_voltage_after_pu", 0)) >= 0.95 - 1e-6,
        opt.get("verified_min_voltage_after_pu"),
        ">= 0.95",
    )
    record_check(
        checks,
        "der_dispatch_within_availability",
        (dispatch["pv_dispatch_mw"] <= dispatch["pv_available_mw"] + 1e-6).all()
        and (dispatch["pv_dispatch_mw"] >= -1e-6).all(),
        "dispatch bounds",
        "0 <= dispatch <= available",
    )
