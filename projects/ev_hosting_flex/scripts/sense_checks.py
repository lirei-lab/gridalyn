"""Objective sense checks for the ``ev_hosting_flex`` study.

These assertions are study knowledge — which artifacts the hosting-capacity
objective produces and what plausible values look like for it — so they live
beside the study and are declared in ``project.yaml`` under
``spec.validation.senseChecker``. The library discovers them there and knows
nothing about this study by name.

Headline pins come from CALIBRATION.md (2026-08-05, 6th re-base): firm hosting
11 EVs (P05-P95 10-13), flexible 16. Checks use error severity only where a
real contract would break; warnings where a number looks off.
"""

from __future__ import annotations

from gridalyn.projects.models import StudyProject
from gridalyn.projects.sense_check_api import (
    CheckList,
    between,
    record_check,
    report_summary,
)


def check(project: StudyProject, checks: CheckList) -> None:
    """Run the flagship's objective plausibility checks."""
    curtailment = report_summary(
        project, "outputs/reports/curtailment_contracts_report.json"
    )
    annual_congestion = report_summary(
        project, "outputs/reports/annual_congestion_report.json"
    )
    topology = report_summary(project, "outputs/reports/topology_cache_report.json")
    fleet = report_summary(project, "outputs/reports/fleet_triage_report.json")

    # Hosting headline pins (CALIBRATION.md): firm ~11 (P05-P95 10-13), flex ~16.
    record_check(
        checks,
        "hosting_firm_ev_count_in_pin_range",
        between(curtailment.get("firm_ev_count"), 10, 13),
        curtailment.get("firm_ev_count"),
        "10 - 13 (P05-P95 firm pin)",
    )
    record_check(
        checks,
        "hosting_flexible_ev_count_around_pin",
        between(curtailment.get("flexible_ev_count"), 14, 18),
        curtailment.get("flexible_ev_count"),
        "14 - 18 (flexible pin ~16)",
    )
    # The flexible count must exceed the firm count (flexibility adds value).
    record_check(
        checks,
        "hosting_flexible_exceeds_firm",
        float(curtailment.get("flexible_ev_count", 0))
        > float(curtailment.get("firm_ev_count", 0)),
        {
            "firm": curtailment.get("firm_ev_count"),
            "flexible": curtailment.get("flexible_ev_count"),
        },
        "flexible > firm",
    )

    # Annual congestion: at firm hosting the P95 loading sits near rating.
    record_check(
        checks,
        "annual_p95_at_firm_below_overload",
        float(annual_congestion.get("p95_at_firm_percent", 999)) <= 110.0,
        annual_congestion.get("p95_at_firm_percent"),
        "<= 110% at firm",
    )
    # Fleet triage: the network genuinely needs deferral action at 1 EV.
    record_check(
        checks,
        "fleet_needs_steel_at_1ev",
        fleet.get("needs_steel_at_1ev") == 1,
        fleet.get("needs_steel_at_1ev"),
        "1 (deferral value present)",
        severity="warning",
    )
    # Topology cache: a real feeder was extracted.
    record_check(
        checks,
        "topology_feeder_has_buses",
        int(topology.get("n_buses", 0)) > 0,
        topology.get("n_buses"),
        "> 0",
    )
    record_check(
        checks,
        "topology_feeder_rating_positive",
        float(topology.get("feeder_transformer_rating_kw", 0)) > 0,
        topology.get("feeder_transformer_rating_kw"),
        "> 0",
    )
