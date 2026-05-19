"""Train a small tabular Q-learning voltage controller with lightsim2grid."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path("outputs/cache/matplotlib").resolve()))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from gridalyn.foundation import ReportMetadata, file_reference, write_report
from gridalyn.simulation import VoltageControlEnvironment

from network_model import (
    ACTION_MW,
    build_rl_environment_spec,
)


PROJECT_NAME = "rl_voltage_control_lightsim"
EPISODE_COUNT = 90
STEP_COUNT = 24
DT_H = 0.25
CONTROLLED_BUS = 9
V_LOW = 0.98
V_HIGH = 1.04


def _state(record: dict, soc_mwh: float, step: int) -> tuple[int, int, int]:
    vm = float(record["controlled_vm_pu"])
    voltage_bin = 0 if vm < 0.995 else 2 if vm > 1.025 else 1
    soc_bin = 0 if soc_mwh < 0.16 else 2 if soc_mwh > 0.30 else 1
    time_bin = step
    return voltage_bin, soc_bin, time_bin


def _q_key(state: tuple[int, int, int], action: float) -> tuple[int, int, int, float]:
    return (*state, float(action))


def _select_action(q: dict, state: tuple[int, int, int], epsilon: float, rng: np.random.Generator) -> float:
    if rng.random() < epsilon:
        return float(rng.choice(ACTION_MW))
    values = [(q.get(_q_key(state, action), 0.0), float(action)) for action in ACTION_MW]
    return max(values, key=lambda item: (item[0], -abs(item[1])))[1]


def _train() -> tuple[dict, pd.DataFrame]:
    q: dict[tuple[int, int, int, float], float] = {}
    for voltage_bin in range(3):
        preferred = ACTION_MW[2] if voltage_bin == 0 else ACTION_MW[0] if voltage_bin == 2 else ACTION_MW[1]
        for soc_bin in range(3):
            for time_bin in range(STEP_COUNT):
                q[_q_key((voltage_bin, soc_bin, time_bin), preferred)] = 0.04
    rng = np.random.default_rng(7)
    episode_rows = []
    alpha = 0.28
    gamma = 0.88

    for episode in range(EPISODE_COUNT):
        env = VoltageControlEnvironment(build_rl_environment_spec())
        env.reset()
        total_reward = 0.0
        prev_record = env.step(0, 0.0)
        state = _state(prev_record, env.soc_mwh, 0)
        for step in range(STEP_COUNT):
            epsilon = 0.0 if episode == 0 else max(0.04, 0.55 * (1.0 - episode / EPISODE_COUNT))
            action = 0.0 if episode == 0 else _select_action(q, state, epsilon, rng)
            record = env.step(step, action)
            next_state = _state(record, env.soc_mwh, step)
            best_next = max(q.get(_q_key(next_state, next_action), 0.0) for next_action in ACTION_MW)
            key = _q_key(state, action)
            q[key] = q.get(key, 0.0) + alpha * (record["reward"] + gamma * best_next - q.get(key, 0.0))
            total_reward += float(record["reward"])
            state = next_state
        episode_rows.append(
            {
                "episode": episode,
                "total_reward": total_reward,
                "epsilon": 0.0 if episode == 0 else max(0.04, 0.55 * (1.0 - episode / EPISODE_COUNT)),
            }
        )
    return q, pd.DataFrame(episode_rows)


def _evaluate(q: dict) -> pd.DataFrame:
    env = VoltageControlEnvironment(build_rl_environment_spec())
    env.reset()
    rows = []
    record = env.step(0, 0.0)
    state = _state(record, env.soc_mwh, 0)
    for step in range(STEP_COUNT):
        action = _select_action(q, state, 0.0, np.random.default_rng(0))
        record = env.step(step, action)
        record["state"] = str(state)
        record["step"] = step
        rows.append(record)
        state = _state(record, env.soc_mwh, step)
    return pd.DataFrame(rows)


def _uncontrolled() -> pd.DataFrame:
    env = VoltageControlEnvironment(build_rl_environment_spec())
    env.reset()
    rows = []
    for step in range(STEP_COUNT):
        rows.append(env.step(step, 0.0))
    return pd.DataFrame(rows)


def _q_table_frame(q: dict) -> pd.DataFrame:
    rows = [
        {
            "voltage_bin": key[0],
            "soc_bin": key[1],
            "time_bin": key[2],
            "action_mw": key[3],
            "q_value": value,
        }
        for key, value in sorted(q.items())
    ]
    return pd.DataFrame(rows)


def _policy_frame(q: dict) -> pd.DataFrame:
    rows = []
    for voltage_bin in range(3):
        for soc_bin in range(3):
            for time_bin in range(STEP_COUNT):
                state = (voltage_bin, soc_bin, time_bin)
                action = _select_action(q, state, 0.0, np.random.default_rng(0))
                rows.append(
                    {
                        "voltage_bin": voltage_bin,
                        "soc_bin": soc_bin,
                        "time_bin": time_bin,
                        "action_mw": action,
                    }
                )
    return pd.DataFrame(rows)


def _write_figure(episodes: pd.DataFrame, controlled: pd.DataFrame, uncontrolled: pd.DataFrame) -> Path:
    figure_path = Path("outputs/figures/rl_voltage_control.png")
    fig, axes = plt.subplots(3, 1, figsize=(9.5, 8.0), gridspec_kw={"height_ratios": [1.0, 1.2, 1.0]})
    axes[0].plot(episodes["episode"], episodes["total_reward"], linewidth=1.7)
    axes[0].set_title("Tabular Q-Learning With LightSim2Grid")
    axes[0].set_ylabel("Episode reward")
    axes[0].grid(True, alpha=0.3)
    axes[1].plot(uncontrolled["step"], uncontrolled["controlled_vm_pu"], marker="o", label="Uncontrolled")
    axes[1].plot(controlled["step"], controlled["controlled_vm_pu"], marker="o", label="Controlled")
    axes[1].axhline(V_HIGH, color="#c0392b", linestyle="--", linewidth=1.1)
    axes[1].axhline(V_LOW, color="#7f8c8d", linestyle=":", linewidth=1.1)
    axes[1].set_ylabel("Bus 9 voltage [p.u.]")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(loc="best")
    axes[2].step(controlled["step"], controlled["action_mw"], where="mid")
    axes[2].set_ylabel("Battery action [MW]")
    axes[2].set_xlabel("Step")
    axes[2].grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(figure_path, dpi=160)
    plt.close(fig)
    return figure_path


def _deviation_sum(frame: pd.DataFrame) -> float:
    return float((frame["controlled_vm_pu"] - 1.01).abs().sum())


def _violation_count(frame: pd.DataFrame) -> int:
    return int(((frame["controlled_vm_pu"] > V_HIGH) | (frame["controlled_vm_pu"] < V_LOW)).sum())


def main() -> int:
    Path("outputs/data").mkdir(parents=True, exist_ok=True)
    Path("outputs/operations").mkdir(parents=True, exist_ok=True)
    Path("outputs/reports").mkdir(parents=True, exist_ok=True)
    Path("outputs/figures").mkdir(parents=True, exist_ok=True)
    q, episodes = _train()
    controlled = _evaluate(q)
    uncontrolled = _uncontrolled()
    q_table = _q_table_frame(q)
    policy = _policy_frame(q)

    episodes_path = Path("outputs/data/training_episodes.csv")
    trajectory_path = Path("outputs/data/policy_evaluation_trajectory.csv")
    q_path = Path("outputs/operations/q_table.csv")
    policy_path = Path("outputs/operations/learned_policy.csv")
    episodes.to_csv(episodes_path, index=False)
    controlled.to_csv(trajectory_path, index=False)
    q_table.to_csv(q_path, index=False)
    policy.to_csv(policy_path, index=False)
    figure_path = _write_figure(episodes, controlled, uncontrolled)

    summary = {
        "algorithm": "tabular_q_learning_voltage_control",
        "simulation_engine": "lightsim2grid",
        "episode_count": EPISODE_COUNT,
        "evaluation_step_count": STEP_COUNT,
        "action_space_mw": list(ACTION_MW),
        "total_reward_first_episode": float(episodes.iloc[0]["total_reward"]),
        "total_reward_last_episode": float(episodes.iloc[-1]["total_reward"]),
        "controlled_voltage_deviation_sum": _deviation_sum(controlled),
        "uncontrolled_voltage_deviation_sum": _deviation_sum(uncontrolled),
        "voltage_violation_count_controlled": _violation_count(controlled),
        "voltage_violation_count_uncontrolled": _violation_count(uncontrolled),
        "max_voltage_controlled_pu": float(controlled["controlled_vm_pu"].max()),
        "max_voltage_uncontrolled_pu": float(uncontrolled["controlled_vm_pu"].max()),
    }
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
