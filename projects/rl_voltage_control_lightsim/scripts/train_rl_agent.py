"""Train a Gridalyn tabular voltage controller and write project artifacts."""

from __future__ import annotations

from network_model import build_rl_environment_spec

from gridalyn.foundation.platform.capabilities import require_capabilities
from gridalyn.projects.scripting import project_script
from gridalyn.simulation import (
    TabularVoltageControlConfig,
    summarize_tabular_voltage_control,
    train_tabular_voltage_controller,
    write_tabular_voltage_control_figure,
)

EPISODE_COUNT = 90
STEP_COUNT = 24
V_LOW = 0.98
V_HIGH = 1.04


def main() -> int:
    script = project_script()
    require_capabilities("sim", context="RL voltage-controller training")
    environment_spec = build_rl_environment_spec()
    # Read rather than inherited. This stage's Q-learning exploration is a
    # second, independent RNG stream from the one that generates the load
    # profiles, and it used to run on TabularVoltageControlConfig's own default
    # (7) which the project declared nowhere -- so the learned policy was
    # governed by a library default no governed artifact recorded. Declaring 7
    # in spec.simulation.seeds.policy and reading it here keeps the declaration
    # and the draw the same value by construction.
    training_config = TabularVoltageControlConfig(
        episode_count=EPISODE_COUNT,
        step_count=STEP_COUNT,
        random_seed=script.simulation_seed("policy"),
    )
    result = train_tabular_voltage_controller(environment_spec, training_config)

    episodes_path = script.data_dir / "training_episodes.csv"
    trajectory_path = script.data_dir / "policy_evaluation_trajectory.csv"
    q_path = script.operations_dir / "q_table.csv"
    policy_path = script.operations_dir / "learned_policy.csv"
    result.episodes.to_csv(episodes_path, index=False)
    result.controlled.to_csv(trajectory_path, index=False)
    result.q_table_frame.to_csv(q_path, index=False)
    result.policy.to_csv(policy_path, index=False)
    figure_path = write_tabular_voltage_control_figure(
        result,
        script.figures_dir / "rl_voltage_control.png",
        voltage_low_pu=V_LOW,
        voltage_high_pu=V_HIGH,
    )

    summary = summarize_tabular_voltage_control(
        result, environment_spec, training_config
    )
    valid = (
        summary["total_reward_last_episode"] > summary["total_reward_first_episode"]
        and summary["controlled_voltage_deviation_sum"]
        < summary["uncontrolled_voltage_deviation_sum"]
    )
    script.write_report(
        "rl_voltage_control_report",
        inputs=[
            script.file_reference(script.data_dir / "rl_assets.csv"),
            {"name": "lightsim2grid_gridmodel", "type": "fast_powerflow_simulator"},
            {
                "name": "loadGeneration",
                "type": "generated_load_profile",
                **dict(script.input("loadGeneration")),
            },
        ],
        artifacts=[
            script.file_reference(episodes_path),
            script.file_reference(trajectory_path),
            script.file_reference(q_path),
            script.file_reference(policy_path),
            script.file_reference(figure_path),
        ],
        summary=summary,
        validation={
            "valid": bool(valid),
            "errors": (
                [] if valid else ["learned policy did not improve voltage objective"]
            ),
            "warnings": [],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
