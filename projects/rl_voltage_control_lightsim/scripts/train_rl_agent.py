"""Train a Gridalyn tabular voltage controller and write project artifacts."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path("outputs/cache/matplotlib").resolve()))

from gridalyn.foundation import ReportMetadata, file_reference, write_report
from gridalyn.simulation import (
    TabularVoltageControlConfig,
    summarize_tabular_voltage_control,
    train_tabular_voltage_controller,
    write_tabular_voltage_control_figure,
)

from network_model import build_rl_environment_spec


PROJECT_NAME = "rl_voltage_control_lightsim"
EPISODE_COUNT = 90
STEP_COUNT = 24
V_LOW = 0.98
V_HIGH = 1.04


def main() -> int:
    Path("outputs/data").mkdir(parents=True, exist_ok=True)
    Path("outputs/operations").mkdir(parents=True, exist_ok=True)
    Path("outputs/reports").mkdir(parents=True, exist_ok=True)
    Path("outputs/figures").mkdir(parents=True, exist_ok=True)
    environment_spec = build_rl_environment_spec()
    training_config = TabularVoltageControlConfig(
        episode_count=EPISODE_COUNT,
        step_count=STEP_COUNT,
    )
    result = train_tabular_voltage_controller(environment_spec, training_config)

    episodes_path = Path("outputs/data/training_episodes.csv")
    trajectory_path = Path("outputs/data/policy_evaluation_trajectory.csv")
    q_path = Path("outputs/operations/q_table.csv")
    policy_path = Path("outputs/operations/learned_policy.csv")
    result.episodes.to_csv(episodes_path, index=False)
    result.controlled.to_csv(trajectory_path, index=False)
    result.q_table_frame.to_csv(q_path, index=False)
    result.policy.to_csv(policy_path, index=False)
    figure_path = write_tabular_voltage_control_figure(
        result,
        "outputs/figures/rl_voltage_control.png",
        voltage_low_pu=V_LOW,
        voltage_high_pu=V_HIGH,
    )

    summary = summarize_tabular_voltage_control(result, environment_spec, training_config)
    valid = (
        summary["total_reward_last_episode"] > summary["total_reward_first_episode"]
        and summary["controlled_voltage_deviation_sum"] < summary["uncontrolled_voltage_deviation_sum"]
    )
    write_report(
        Path("outputs/reports/rl_voltage_control_report.json"),
        metadata=ReportMetadata(
            report_id="rl_voltage_control_report",
            source_domain=PROJECT_NAME,
            project={"name": PROJECT_NAME},
        ),
        inputs=[
            file_reference("outputs/data/rl_assets.csv"),
            {"name": "lightsim2grid_gridmodel", "type": "fast_powerflow_simulator"},
        ],
        artifacts=[
            file_reference(episodes_path),
            file_reference(trajectory_path),
            file_reference(q_path),
            file_reference(policy_path),
            file_reference(figure_path),
        ],
        summary=summary,
        validation={
            "valid": bool(valid),
            "errors": [] if valid else ["learned policy did not improve voltage objective"],
            "warnings": [],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
