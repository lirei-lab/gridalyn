"""Objective sense checks for the ``dr_agent_interaction`` study.

Declared in ``project.yaml`` under ``spec.validation.senseChecker``. They check
that the day is the day the study claims to run: every home had a conversation
per event, the channel actually lost messages, the program actually curtailed,
and the two reports agree on how many messages there were.
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

_PROGRAM = "outputs/reports/dr_program_report.json"
_INTERACTION = "outputs/reports/dr_interaction_report.json"


def check(project: StudyProject, checks: CheckList) -> None:
    program = report_summary(project, _PROGRAM)
    interaction = report_summary(project, _INTERACTION)
    conversations = read_csv(project, "outputs/operations/dr_conversations.csv")
    expected = int(program.get("home_count", 0)) * int(program.get("event_count", 0))
    record_check(
        checks,
        "dr_one_conversation_per_home_and_event",
        expected > 0 and len(conversations) == expected,
        len(conversations),
        f"home_count x event_count = {expected}",
    )
    record_check(
        checks,
        "dr_reports_agree_on_message_count",
        program.get("message_count") == interaction.get("message_count"),
        {
            "program": program.get("message_count"),
            "interaction": interaction.get("message_count"),
        },
        "equal",
    )
    record_check(
        checks,
        "dr_channel_is_lossy",
        int(program.get("lost_message_count", 0)) > 0,
        program.get("lost_message_count"),
        "> 0: the study declares a lossy channel",
    )
    record_check(
        checks,
        "dr_response_rate_is_a_rate",
        between(program.get("response_rate"), 0.0, 1.0),
        program.get("response_rate"),
        "within [0, 1]",
    )
    record_check(
        checks,
        "dr_program_curtails",
        float(program.get("delivered_kwh", 0.0)) > 0.0,
        program.get("delivered_kwh"),
        "> 0 kWh",
    )
    record_check(
        checks,
        "dr_event_peak_reduced",
        float(program.get("peak_program_kw", float("inf")))
        < float(program.get("peak_baseline_kw", 0.0)),
        {
            "program": program.get("peak_program_kw"),
            "baseline": program.get("peak_baseline_kw"),
        },
        "program peak below baseline peak",
    )
    record_check(
        checks,
        "dr_opt_outs_delivered_not_above_decided",
        int(program.get("opt_out_delivered_count", 0))
        <= int(program.get("opt_out_decision_count", 0)),
        {
            "delivered": program.get("opt_out_delivered_count"),
            "decided": program.get("opt_out_decision_count"),
        },
        "delivered <= decided",
    )
