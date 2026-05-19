# RL Voltage Control With LightSim2Grid

This project demonstrates a small reinforcement-learning loop for distribution
voltage control. A tabular Q-learning agent controls a battery at the end of a
synthetic radial feeder. `lightsim2grid` runs the power-flow simulation inside
training and evaluation.

## Run

```bash
uv run gridalyn project run projects/rl_voltage_control_lightsim
uv run gridalyn project status projects/rl_voltage_control_lightsim --check-artifacts
```

## Outputs

- `outputs/data/training_episodes.csv`: episode reward history.
- `outputs/data/policy_evaluation_trajectory.csv`: greedy policy trajectory.
- `outputs/operations/q_table.csv`: learned tabular Q-values.
- `outputs/operations/learned_policy.csv`: best action by discrete state.
- `outputs/reports/rl_voltage_control_report.json`: report with learning and voltage metrics.
- `outputs/figures/rl_voltage_control.png`: voltage/action/reward summary.

## Scope

This is intentionally a small RL example. It is not a production controller.
The purpose is to show how Gridalyn can package learning, fast simulation, and
grid verification into the same project contract used by other studies.
