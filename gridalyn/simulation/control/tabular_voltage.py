"""Tabular voltage-control training over Gridalyn simulation environments."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from gridalyn.simulation.environments import (
    VoltageControlEnvironment,
    VoltageControlEnvironmentSpec,
)


@dataclass(frozen=True)
class TabularVoltageControlConfig:
    """Configuration for a compact tabular voltage-control policy."""

    episode_count: int = 90
    step_count: int = 24
    alpha: float = 0.28
    gamma: float = 0.88
    random_seed: int = 7
    baseline_epsilon: float = 0.0
    initial_epsilon: float = 0.55
    min_epsilon: float = 0.04
    voltage_low_bin_pu: float = 0.995
    voltage_high_bin_pu: float = 1.025
    soc_low_bin_mwh: float = 0.16
    soc_high_bin_mwh: float = 0.30


@dataclass(frozen=True)
class TabularVoltageControlResult:
    """Tables produced by training and evaluating a tabular voltage controller."""

    q_table: dict[tuple[int, int, int, float], float]
    episodes: pd.DataFrame
    controlled: pd.DataFrame
    uncontrolled: pd.DataFrame
    q_table_frame: pd.DataFrame
    policy: pd.DataFrame


def train_tabular_voltage_controller(
    spec: VoltageControlEnvironmentSpec,
    config: TabularVoltageControlConfig = TabularVoltageControlConfig(),
) -> TabularVoltageControlResult:
    """Train and evaluate a tabular Q-learning voltage controller."""
    q_table, episodes = _train(spec, config)
    controlled = _evaluate(spec, config, q_table)
    uncontrolled = _uncontrolled(spec, config)
    return TabularVoltageControlResult(
        q_table=q_table,
        episodes=episodes,
        controlled=controlled,
        uncontrolled=uncontrolled,
        q_table_frame=_q_table_frame(q_table),
        policy=_policy_frame(spec, config, q_table),
    )


def summarize_tabular_voltage_control(
    result: TabularVoltageControlResult,
    spec: VoltageControlEnvironmentSpec,
    config: TabularVoltageControlConfig = TabularVoltageControlConfig(),
) -> dict:
    """Build the canonical report summary for a tabular voltage-control run."""
    action_space = [float(action) for action in spec.der.action_space_mw]
    return {
        "algorithm": "tabular_q_learning_voltage_control",
        "simulation_engine": "lightsim2grid",
        "episode_count": int(config.episode_count),
        "evaluation_step_count": int(config.step_count),
        "action_space_mw": action_space,
        "total_reward_first_episode": float(result.episodes.iloc[0]["total_reward"]),
        "total_reward_last_episode": float(result.episodes.iloc[-1]["total_reward"]),
        "controlled_voltage_deviation_sum": _deviation_sum(result.controlled, spec.voltage_target_pu),
        "uncontrolled_voltage_deviation_sum": _deviation_sum(result.uncontrolled, spec.voltage_target_pu),
        "voltage_violation_count_controlled": _violation_count(
            result.controlled,
            voltage_high_pu=spec.voltage_high_pu,
            voltage_low_pu=spec.voltage_low_pu,
        ),
        "voltage_violation_count_uncontrolled": _violation_count(
            result.uncontrolled,
            voltage_high_pu=spec.voltage_high_pu,
            voltage_low_pu=spec.voltage_low_pu,
        ),
        "max_voltage_controlled_pu": float(result.controlled["controlled_vm_pu"].max()),
        "max_voltage_uncontrolled_pu": float(result.uncontrolled["controlled_vm_pu"].max()),
    }


def write_tabular_voltage_control_figure(
    result: TabularVoltageControlResult,
    path: str | Path,
    *,
    voltage_low_pu: float,
    voltage_high_pu: float,
) -> Path:
    """Write the canonical tabular voltage-control training figure."""
    from gridalyn.simulation import configure_headless_matplotlib

    configure_headless_matplotlib()
    import matplotlib.pyplot as plt

    figure_path = Path(path)
    figure_path.parent.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(
        3,
        1,
        figsize=(9.5, 8.0),
        gridspec_kw={"height_ratios": [1.0, 1.2, 1.0]},
    )
    axes[0].plot(result.episodes["episode"], result.episodes["total_reward"], linewidth=1.7)
    axes[0].set_title("Tabular Q-Learning With LightSim2Grid")
    axes[0].set_ylabel("Episode reward")
    axes[0].grid(True, alpha=0.3)
    axes[1].plot(
        result.uncontrolled["step"],
        result.uncontrolled["controlled_vm_pu"],
        marker="o",
        label="Uncontrolled",
    )
    axes[1].plot(
        result.controlled["step"],
        result.controlled["controlled_vm_pu"],
        marker="o",
        label="Controlled",
    )
    axes[1].axhline(voltage_high_pu, color="#c0392b", linestyle="--", linewidth=1.1)
    axes[1].axhline(voltage_low_pu, color="#7f8c8d", linestyle=":", linewidth=1.1)
    axes[1].set_ylabel("Controlled bus voltage [p.u.]")
    axes[1].grid(True, alpha=0.3)
    axes[1].legend(loc="best")
    axes[2].step(result.controlled["step"], result.controlled["action_mw"], where="mid")
    axes[2].set_ylabel("Battery action [MW]")
    axes[2].set_xlabel("Step")
    axes[2].grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(figure_path, dpi=160)
    plt.close(fig)
    return figure_path


def _state(
    record: dict,
    soc_mwh: float,
    step: int,
    config: TabularVoltageControlConfig,
) -> tuple[int, int, int]:
    vm = float(record["controlled_vm_pu"])
    voltage_bin = 0 if vm < config.voltage_low_bin_pu else 2 if vm > config.voltage_high_bin_pu else 1
    soc_bin = 0 if soc_mwh < config.soc_low_bin_mwh else 2 if soc_mwh > config.soc_high_bin_mwh else 1
    return voltage_bin, soc_bin, step


def _q_key(state: tuple[int, int, int], action: float) -> tuple[int, int, int, float]:
    return (*state, float(action))


def _select_action(
    q_table: dict[tuple[int, int, int, float], float],
    state: tuple[int, int, int],
    action_space: tuple[float, ...],
    epsilon: float,
    rng: np.random.Generator,
) -> float:
    if rng.random() < epsilon:
        return float(rng.choice(action_space))
    values = [(q_table.get(_q_key(state, action), 0.0), float(action)) for action in action_space]
    return max(values, key=lambda item: (item[0], -abs(item[1])))[1]


def _seed_q_table(
    action_space: tuple[float, ...],
    step_count: int,
) -> dict[tuple[int, int, int, float], float]:
    q_table: dict[tuple[int, int, int, float], float] = {}
    charge_action = min(action_space)
    neutral_action = min(action_space, key=abs)
    discharge_action = max(action_space)
    for voltage_bin in range(3):
        preferred = discharge_action if voltage_bin == 0 else charge_action if voltage_bin == 2 else neutral_action
        for soc_bin in range(3):
            for time_bin in range(step_count):
                q_table[_q_key((voltage_bin, soc_bin, time_bin), preferred)] = 0.04
    return q_table


def _train(
    spec: VoltageControlEnvironmentSpec,
    config: TabularVoltageControlConfig,
) -> tuple[dict[tuple[int, int, int, float], float], pd.DataFrame]:
    action_space = tuple(float(action) for action in spec.der.action_space_mw)
    q_table = _seed_q_table(action_space, config.step_count)
    rng = np.random.default_rng(config.random_seed)
    episode_rows = []

    for episode in range(config.episode_count):
        env = VoltageControlEnvironment(spec)
        env.reset()
        total_reward = 0.0
        prev_record = env.step(0, 0.0)
        state = _state(prev_record, env.soc_mwh, 0, config)
        epsilon = _episode_epsilon(episode, config)
        for step in range(config.step_count):
            action = 0.0 if episode == 0 else _select_action(q_table, state, action_space, epsilon, rng)
            record = env.step(step, action)
            next_state = _state(record, env.soc_mwh, step, config)
            best_next = max(q_table.get(_q_key(next_state, next_action), 0.0) for next_action in action_space)
            key = _q_key(state, action)
            q_table[key] = q_table.get(key, 0.0) + config.alpha * (
                record["reward"] + config.gamma * best_next - q_table.get(key, 0.0)
            )
            total_reward += float(record["reward"])
            state = next_state
        episode_rows.append(
            {
                "episode": episode,
                "total_reward": total_reward,
                "epsilon": epsilon,
            }
        )
    return q_table, pd.DataFrame(episode_rows)


def _evaluate(
    spec: VoltageControlEnvironmentSpec,
    config: TabularVoltageControlConfig,
    q_table: dict[tuple[int, int, int, float], float],
) -> pd.DataFrame:
    action_space = tuple(float(action) for action in spec.der.action_space_mw)
    env = VoltageControlEnvironment(spec)
    env.reset()
    rows = []
    record = env.step(0, 0.0)
    state = _state(record, env.soc_mwh, 0, config)
    for step in range(config.step_count):
        action = _select_action(q_table, state, action_space, 0.0, np.random.default_rng(0))
        record = env.step(step, action)
        record["state"] = str(state)
        record["step"] = step
        rows.append(record)
        state = _state(record, env.soc_mwh, step, config)
    return pd.DataFrame(rows)


def _uncontrolled(
    spec: VoltageControlEnvironmentSpec,
    config: TabularVoltageControlConfig,
) -> pd.DataFrame:
    env = VoltageControlEnvironment(spec)
    env.reset()
    rows = []
    for step in range(config.step_count):
        rows.append(env.step(step, 0.0))
    return pd.DataFrame(rows)


def _q_table_frame(q_table: dict[tuple[int, int, int, float], float]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "voltage_bin": key[0],
                "soc_bin": key[1],
                "time_bin": key[2],
                "action_mw": key[3],
                "q_value": value,
            }
            for key, value in sorted(q_table.items())
        ]
    )


def _policy_frame(
    spec: VoltageControlEnvironmentSpec,
    config: TabularVoltageControlConfig,
    q_table: dict[tuple[int, int, int, float], float],
) -> pd.DataFrame:
    action_space = tuple(float(action) for action in spec.der.action_space_mw)
    rows = []
    for voltage_bin in range(3):
        for soc_bin in range(3):
            for time_bin in range(config.step_count):
                state = (voltage_bin, soc_bin, time_bin)
                action = _select_action(q_table, state, action_space, 0.0, np.random.default_rng(0))
                rows.append(
                    {
                        "voltage_bin": voltage_bin,
                        "soc_bin": soc_bin,
                        "time_bin": time_bin,
                        "action_mw": action,
                    }
                )
    return pd.DataFrame(rows)


def _episode_epsilon(episode: int, config: TabularVoltageControlConfig) -> float:
    if episode == 0:
        return config.baseline_epsilon
    return max(config.min_epsilon, config.initial_epsilon * (1.0 - episode / config.episode_count))


def _deviation_sum(frame: pd.DataFrame, voltage_target_pu: float) -> float:
    return float((frame["controlled_vm_pu"] - voltage_target_pu).abs().sum())


def _violation_count(
    frame: pd.DataFrame,
    *,
    voltage_high_pu: float,
    voltage_low_pu: float,
) -> int:
    return int(
        (
            (frame["controlled_vm_pu"] > voltage_high_pu)
            | (frame["controlled_vm_pu"] < voltage_low_pu)
        ).sum()
    )


__all__ = [
    "TabularVoltageControlConfig",
    "TabularVoltageControlResult",
    "summarize_tabular_voltage_control",
    "train_tabular_voltage_controller",
    "write_tabular_voltage_control_figure",
]
