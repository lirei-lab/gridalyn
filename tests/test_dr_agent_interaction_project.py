"""Gates for the ``dr_agent_interaction`` fixture study (syntgrid-4ky.9).

The study exists to put the ``dr_program`` protocol under a contract CI enforces:
its baseline pins protocol metrics, so a change to a protocol transition must
move them. This module proves both halves in-process, in seconds:

* **the pins are live** -- an unmutated day passes the study's own regression
  baseline, and a day run under a mutated ``dr_program`` transition fails it,
  through the same ``build_regression_report`` the CI ``projects`` job uses;
* **the day is not vacuous** -- a lossy channel lost messages, homes opted out,
  a cancellation landed and the response rate is strictly between 0 and 1; a
  day with an ideal channel and no comfort limit trips those floors, so they
  would catch a study that silently stopped exercising the protocol.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

from gridalyn.operations.interaction import conversations
from gridalyn.operations.interaction.dr_program import (
    ACTIVE_UNTIL_FIELD,
    DR_PROGRAM_PROTOCOL,
)
from gridalyn.operations.interaction.protocols import (
    DeadlineTransition,
    MessageTransition,
)
from gridalyn.projects import run_workflow, validate_project
from gridalyn.projects.loader import load_project
from gridalyn.projects.regression import build_regression_report, run_project_regression
from gridalyn.projects.runner import plan_stages
from gridalyn.projects.scripting import project_script
from gridalyn.simulation.channels import IdealChannel

PROJECT_ROOT = Path(__file__).resolve().parents[1] / "projects" / "dr_agent_interaction"
BASELINE = PROJECT_ROOT / "baselines" / "results_baseline.json"
REPORT = "outputs/reports/dr_program_report.json"


def _program_day_module():
    name = "dr_agent_interaction_program_day"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, PROJECT_ROOT / "scripts" / "program_day.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _summary(*, channel=None, program=None):
    module = _program_day_module()
    script = project_script(root=PROJECT_ROOT)
    day = module.simulate_program_day(
        program=program or script.load_demand_response_program(),
        channel=channel if channel is not None else script.channel_model(),
        seed=script.simulation_seed("agents"),
    )
    return module.summarize_program_day(day)


def _regression(summary, tmp_path: Path) -> dict:
    # build_regression_report reads the baseline relative to the project root,
    # so the committed baseline is copied beside the summary under test.
    report = tmp_path / REPORT
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({"summary": summary}), encoding="utf-8")
    baseline = tmp_path / "baselines" / BASELINE.name
    baseline.parent.mkdir(parents=True)
    baseline.write_bytes(BASELINE.read_bytes())
    return build_regression_report(project_root=tmp_path, baseline_path=baseline)


def _floor_failures(summary) -> list[str]:
    states = summary["conversation_states"]
    cancelled = sum(counts.get("cancelled", 0) for counts in states.values())
    floors = {
        "a lossy channel lost at least one message": summary["lost_message_count"] >= 1,
        "at least one home opted out": summary["opt_out_decision_count"] >= 1,
        "at least one cancellation was delivered": cancelled >= 1,
        "at least one report arrived": summary["report_count"] >= 1,
        "the response rate is strictly between 0 and 1": 0.0
        < summary["response_rate"]
        < 1.0,
        "the program curtailed": summary["delivered_kwh"] > 0.0,
    }
    return [floor for floor, held in floors.items() if not held]


@pytest.fixture(scope="module")
def summary():
    return _summary()


def test_the_study_contract_is_valid_and_its_workflow_small():
    report = validate_project(PROJECT_ROOT)
    assert report.valid, report.errors
    stages = [
        stage.id for stage in plan_stages(load_project(PROJECT_ROOT / "project.yaml"))
    ]
    assert stages == [
        "prepare_workspace",
        "run_dr_program_day",
        "validate_project_outputs",
    ]


def test_the_stage_runs_end_to_end_and_passes_its_regression(monkeypatch):
    # Stages are subprocesses that import gridalyn from the environment; point
    # them at this checkout, so a worktree runs its own library code.
    repo_root = str(PROJECT_ROOT.parents[1])
    inherited = os.environ.get("PYTHONPATH")
    monkeypatch.setenv(
        "PYTHONPATH", os.pathsep.join(part for part in (repo_root, inherited) if part)
    )
    run_workflow(PROJECT_ROOT)
    regression = run_project_regression(project_root=PROJECT_ROOT)
    assert regression["valid"], regression["errors"]
    interaction = json.loads(
        (PROJECT_ROOT / "outputs/reports/dr_interaction_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert interaction["validation"]["valid"] is True
    assert interaction["summary"]["lost_message_count"] > 0


def test_an_unmutated_day_passes_the_committed_baseline(summary, tmp_path):
    report = _regression(summary, tmp_path)
    assert report["checked_count"] >= 10
    assert report["valid"], report["errors"]


def test_the_day_is_not_vacuous(summary):
    assert _floor_failures(summary) == [], (
        "the fixture no longer exercises the protocol it pins; a study that "
        "loses no message, has no opt-out and no cancellation proves nothing"
    )


def test_a_degenerate_day_trips_the_floors():
    module = _program_day_module()
    program = project_script(root=PROJECT_ROOT).load_demand_response_program()
    calm = dataclasses.replace(program, opt_out_below_indoor_c=None)
    failures = _floor_failures(_summary(channel=IdealChannel(), program=calm))
    assert "a lossy channel lost at least one message" in failures
    assert "at least one home opted out" in failures
    assert module.STEP_MINUTES == 5


def _mutated(**changes):
    mutated = dataclasses.replace(DR_PROGRAM_PROTOCOL, **changes)

    def resolve(protocol_id: str):
        if protocol_id == "dr_program":
            return mutated
        return conversations.PROTOCOLS[protocol_id]

    return resolve


_ACTIVATES_AT_THE_END = _mutated(
    deadline_transitions=(
        DeadlineTransition("notified", ACTIVE_UNTIL_FIELD, "active"),
        *DR_PROGRAM_PROTOCOL.deadline_transitions[1:],
    )
)
_RUNNING_OPT_OUT_IGNORED = _mutated(
    transitions=tuple(
        (
            MessageTransition(
                edge.source,
                edge.message_type,
                edge.performative,
                edge.sender_roles,
                edge.receiver_roles,
                "active",
            )
            if (edge.source, edge.message_type) == ("active", "flexint:OptOut")
            else edge
        )
        for edge in DR_PROGRAM_PROTOCOL.transitions
    )
)


@pytest.mark.parametrize(
    "resolver",
    [_ACTIVATES_AT_THE_END, _RUNNING_OPT_OUT_IGNORED],
    ids=["event-activates-at-its-end", "running-opt-out-ignored"],
)
def test_a_mutated_protocol_transition_turns_the_regression_red(
    resolver, monkeypatch, tmp_path
):
    monkeypatch.setattr(conversations, "resolve_protocol", resolver)
    report = _regression(_summary(), tmp_path)
    assert not report["valid"]
    failed = {check["id"] for check in report["checks"] if not check["valid"]}
    assert "summary.conversation_states" in failed
