# RL Voltage Control With LightSim2Grid

This project demonstrates a small reinforcement-learning loop for distribution
voltage control. Gridalyn's tabular voltage-control trainer controls a battery
at the end of a synthetic radial feeder. `lightsim2grid` runs the power-flow
simulation inside training and evaluation.

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

---

<!-- Merged from the former docs/projects/rl-voltage-control-lightsim.md. The published
documentation now covers the project CONTRACT in general; per-project
detail lives with the project. -->

`projects/rl_voltage_control_lightsim` is a compact learning-control demo. It
uses a tabular Q-learning agent to control a battery on a synthetic radial
feeder, while `lightsim2grid` provides the fast AC power-flow simulation loop.

## Why This Demo Exists

The other demos show deterministic simulation, markets, and convex
optimization. This project adds a learning-based control pattern:

- build a synthetic feeder;
- create PV and battery control assets;
- model the feeder and DER through Gridalyn asset contracts;
- run a reusable Gridalyn voltage-control environment backed by `lightsim2grid`;
- train a small tabular controller through Gridalyn's reusable control module;
- evaluate the learned policy against an uncontrolled baseline;
- publish episode history, policy, Q-table, trajectory, report, and figure.

The result is intentionally small and inspectable. It is not a production RL
controller; it is a platform example for packaging learning experiments with
grid simulation and reproducible artifacts.

## Run It

```bash
uv run gridalyn project run projects/rl_voltage_control_lightsim
uv run gridalyn project status projects/rl_voltage_control_lightsim --check-artifacts
```

Expected generated artifacts:

```text
projects/rl_voltage_control_lightsim/outputs/data/training_episodes.csv
projects/rl_voltage_control_lightsim/outputs/data/policy_evaluation_trajectory.csv
projects/rl_voltage_control_lightsim/outputs/operations/q_table.csv
projects/rl_voltage_control_lightsim/outputs/operations/learned_policy.csv
projects/rl_voltage_control_lightsim/outputs/reports/rl_voltage_control_report.json
projects/rl_voltage_control_lightsim/outputs/figures/rl_voltage_control.png
projects/rl_voltage_control_lightsim/outputs/manifests/project_run_manifest.json
```

## Workflow

| Stage | Purpose |
| --- | --- |
| `prepare_workspace` | Creates output folders. |
| `build_rl_feeder` | Builds a 10-bus radial feeder through `RadialFeederSpec`, initializes the Gridalyn LightSim adapter, and writes feeder assets/report/figure. |
| `train_rl_voltage_agent` | Calls Gridalyn's tabular voltage-control trainer against `VoltageControlEnvironment`, evaluates the greedy policy, and writes learning/control artifacts. |

## Gridalyn SDK Usage

The project keeps workflow wiring locally and declares its concrete feeder, DER
contract, and deterministic 24-step load/PV profiles in `project.yaml`. The
project wrapper loads that contract through `gridalyn.projects` model-input
helpers.

The reusable network, environment, and tabular training pieces come from
Gridalyn:

```python
from gridalyn.projects import (
    load_radial_feeder_spec,
    load_voltage_control_der_spec,
)
from gridalyn.simulation import (
    TabularVoltageControlConfig,
    VoltageControlEnvironment,
    build_voltage_control_feeder,
    train_tabular_voltage_controller,
)
```

This boundary matters. A new learning-control study should be able to reuse the
same feeder, DER, and environment contracts while swapping the controller from
tabular Q-learning to MPC, safe RL, or a rules-based policy.

## RL Formulation

The state is discrete:

- voltage bin at the controlled downstream bus;
- battery state-of-charge bin;
- time-step index.

The action space is:

```text
[-0.12, 0.0, 0.12] MW
```

Negative action charges the battery; positive action discharges. The reward
penalizes voltage-band violation, voltage deviation from nominal, and battery
movement. The learned policy is compared against an uncontrolled baseline over
the same 24-step load/PV profile.

## Platform Lesson

This demo shows how Gridalyn can host learning experiments without turning the
platform into a notebook collection or a set of standalone scripts:

```text
network model -> fast simulator -> agent training -> policy artifact -> report
```

The same structure can later support Grid2Op-style environments, richer control
domains, safety filters, and physical validation against pandapower or utility
models.
