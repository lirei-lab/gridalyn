"""Objective sense checks for the ``admm_thermal_consensus`` study.

These assertions are study knowledge — which artifacts the coordination
objective produces and what plausible values look like for it — so they live
beside the study and are declared in ``project.yaml`` under
``spec.validation.senseChecker``.

The imputation comparison is saturated (coordinated schedule leaves ~0.5 points
of headroom), so methods are compared on realized peak, not P(violation) — per
CLAUDE.md. The headline value is the ideal peak-reduction fraction vs the
uncoordinated baseline, not a violation probability.
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
    """Run the ADMM coordination objective plausibility checks."""
    admm = report_summary(project, "outputs/reports/admm_report.json")
    network = report_summary(project, "outputs/reports/network_report.json")
    powerflow = report_summary(project, "outputs/reports/powerflow_report.json")
    agents = report_summary(project, "outputs/reports/agents_report.json")

    # Coordination headline: ideal peak reduction vs uncoordinated baseline.
    record_check(
        checks,
        "admm_ideal_peak_reduction_positive",
        float(admm.get("ideal_peak_reduction_fraction", 0)) > 0.05,
        admm.get("ideal_peak_reduction_fraction"),
        "> 0.05 (real reduction)",
    )
    record_check(
        checks,
        "admm_ideal_peak_below_uncoordinated",
        float(admm.get("coordinated_ideal_peak_kw", 1e9))
        < float(admm.get("uncoordinated_peak_kw", 0)),
        {
            "coordinated": admm.get("coordinated_ideal_peak_kw"),
            "uncoordinated": admm.get("uncoordinated_peak_kw"),
        },
        "coordinated < uncoordinated",
    )
    # The coordinated PAR must be near 1.0 (peak flattening is the objective).
    record_check(
        checks,
        "admm_ideal_par_near_one",
        between(admm.get("ideal_par"), 1.0, 1.1),
        admm.get("ideal_par"),
        "1.0 - 1.1",
    )

    # Network: transformer loading before coordination is over-rated.
    record_check(
        checks,
        "network_uncoordinated_transformer_overloaded",
        float(network.get("uncoordinated_transformer_loading_pct", 0)) > 100.0,
        network.get("uncoordinated_transformer_loading_pct"),
        "> 100% before coordination",
    )
    # Power flow: coordination relieves the worst voltage / loading.
    record_check(
        checks,
        "powerflow_ideal_worst_voltage_above_limit",
        float(powerflow.get("ideal_worst_min_voltage_pu", 0)) >= 0.90,
        powerflow.get("ideal_worst_min_voltage_pu"),
        ">= 0.90 pu",
    )
    record_check(
        checks,
        "powerflow_ideal_loading_below_limit",
        float(powerflow.get("ideal_worst_transformer_loading_pct", 999))
        <= float(powerflow.get("transformer_loading_limit_pct", 105)),
        {
            "worst": powerflow.get("ideal_worst_transformer_loading_pct"),
            "limit": powerflow.get("transformer_loading_limit_pct"),
        },
        "ideal worst loading <= declared limit",
    )

    # Agents: a real population with a positive heating load.
    record_check(
        checks,
        "agents_population_present",
        int(agents.get("n_agents", 0)) > 0,
        agents.get("n_agents"),
        "> 0",
    )
    record_check(
        checks,
        "agents_heating_positive",
        float(agents.get("total_heating_kwh", 0)) > 0,
        agents.get("total_heating_kwh"),
        "> 0",
    )
