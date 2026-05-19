import json
from pathlib import Path

import pandas as pd

from gridalyn.platform import project_status, run_workflow, validate_project
from gridalyn.projects.loader import load_project
from gridalyn.projects.runner import plan_stages


PROJECT_ROOT = Path("projects/rl_voltage_control_lightsim")


def test_rl_voltage_control_lightsim_project_contract_is_valid() -> None:
    report = validate_project(PROJECT_ROOT)

    assert report.valid, report.errors


def test_rl_voltage_control_lightsim_workflow_is_small_and_explicit() -> None:
    project = load_project(PROJECT_ROOT / "project.yaml")
    stages = [stage.id for stage in plan_stages(project)]

    assert stages == [
        "prepare_workspace",
        "build_rl_feeder",
        "train_rl_voltage_agent",
    ]


def test_rl_voltage_control_lightsim_runs_end_to_end() -> None:
    executed = run_workflow(PROJECT_ROOT)
    status = project_status(PROJECT_ROOT, check_artifacts=True)

    feeder_report = PROJECT_ROOT / "outputs" / "reports" / "rl_feeder_report.json"
    rl_report = PROJECT_ROOT / "outputs" / "reports" / "rl_voltage_control_report.json"
    q_table_path = PROJECT_ROOT / "outputs" / "operations" / "q_table.csv"
    policy_path = PROJECT_ROOT / "outputs" / "operations" / "learned_policy.csv"
    trajectory_path = PROJECT_ROOT / "outputs" / "data" / "policy_evaluation_trajectory.csv"
    episodes_path = PROJECT_ROOT / "outputs" / "data" / "training_episodes.csv"
    figure_path = PROJECT_ROOT / "outputs" / "figures" / "rl_voltage_control.png"

    feeder = json.loads(feeder_report.read_text(encoding="utf-8"))
    report = json.loads(rl_report.read_text(encoding="utf-8"))
    q_table = pd.read_csv(q_table_path)
    policy = pd.read_csv(policy_path)
    trajectory = pd.read_csv(trajectory_path)
    episodes = pd.read_csv(episodes_path)

    assert executed == [
        "prepare_workspace",
        "build_rl_feeder",
        "train_rl_voltage_agent",
    ]
    assert status["valid"], status
    assert status["reports"]["ready"], status["reports"]
    assert feeder["summary"]["simulation_engine"] == "lightsim2grid"
    assert feeder["summary"]["bus_count"] == 10
    assert report["summary"]["algorithm"] == "tabular_q_learning_voltage_control"
    assert report["summary"]["simulation_engine"] == "lightsim2grid"
    assert report["summary"]["episode_count"] == 90
    assert report["summary"]["evaluation_step_count"] == 24
    assert report["summary"]["total_reward_last_episode"] > report["summary"]["total_reward_first_episode"]
    assert report["summary"]["voltage_violation_count_controlled"] <= report["summary"]["voltage_violation_count_uncontrolled"]
    assert report["summary"]["controlled_voltage_deviation_sum"] < report["summary"]["uncontrolled_voltage_deviation_sum"]
    assert not q_table.empty
    assert set(q_table["action_mw"]).issuperset({-0.12, 0.0, 0.12})
    assert not policy.empty
    assert len(trajectory) == 24
    assert len(episodes) == 90
    assert figure_path.exists()
