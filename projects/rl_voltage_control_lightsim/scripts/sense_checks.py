"""Objective sense checks for the ``rl_voltage_control_lightsim`` study.

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
    feeder = report_summary(project, "outputs/reports/rl_feeder_report.json")
    report = report_summary(project, "outputs/reports/rl_voltage_control_report.json")
    q_table = read_csv(project, "outputs/operations/q_table.csv")
    policy = read_csv(project, "outputs/operations/learned_policy.csv")
    record_check(
        checks,
        "rl_engine_is_lightsim2grid",
        feeder.get("simulation_engine") == "lightsim2grid"
        and report.get("simulation_engine") == "lightsim2grid",
        {
            "feeder": feeder.get("simulation_engine"),
            "control": report.get("simulation_engine"),
        },
        "lightsim2grid",
    )
    record_check(
        checks,
        "rl_algorithm_is_q_learning",
        report.get("algorithm") == "tabular_q_learning_voltage_control",
        report.get("algorithm"),
        "tabular_q_learning_voltage_control",
    )
    record_check(
        checks,
        "rl_training_has_enough_episodes",
        int(report.get("episode_count", 0)) >= 50,
        report.get("episode_count"),
        ">= 50",
    )
    record_check(
        checks,
        "rl_evaluation_is_day_profile",
        report.get("evaluation_step_count") == 24,
        report.get("evaluation_step_count"),
        24,
    )
    record_check(
        checks,
        "rl_reward_improves",
        float(report.get("total_reward_last_episode", -1e9))
        > float(report.get("total_reward_first_episode", 1e9)),
        {
            "first": report.get("total_reward_first_episode"),
            "last": report.get("total_reward_last_episode"),
        },
        "last > first",
    )
    record_check(
        checks,
        "rl_control_reduces_violations",
        int(report.get("voltage_violation_count_controlled", 999))
        <= int(report.get("voltage_violation_count_uncontrolled", 0)),
        report.get("voltage_violation_count_controlled"),
        "<= uncontrolled",
    )
    record_check(
        checks,
        "rl_control_reduces_voltage_deviation",
        float(report.get("controlled_voltage_deviation_sum", 999))
        < float(report.get("uncontrolled_voltage_deviation_sum", 0)),
        report.get("controlled_voltage_deviation_sum"),
        "< uncontrolled",
    )
    record_check(
        checks,
        "rl_action_space_has_charge_neutral_discharge",
        set(round(float(v), 2) for v in q_table["action_mw"].unique()).issuperset(
            {-0.12, 0.0, 0.12}
        ),
        sorted(q_table["action_mw"].unique()),
        "charge, neutral, discharge",
    )
    record_check(
        checks,
        "rl_policy_tables_non_empty",
        not q_table.empty and not policy.empty,
        {"q_table": len(q_table), "policy": len(policy)},
        "non-empty",
    )
