# RL Voltage Control With LightSim2Grid

A compact learning-control study: a tabular Q-learning agent controls a battery
at the end of a synthetic radial feeder, with `lightsim2grid` providing the fast
AC power flow inside training and evaluation.

## What this study asks

Whether a learning experiment can live inside the platform's contract rather
than beside it as a notebook. The other studies show deterministic simulation,
markets and convex optimization; this one adds the learning pattern, end to
end:

```text
network model -> fast simulator -> agent training -> policy artifact -> report
```

Within one governed project it builds a synthetic feeder, declares PV and
battery control assets through the asset contracts, runs a reusable
voltage-control environment backed by `lightsim2grid`, trains a small tabular
controller, evaluates the learned policy against an uncontrolled baseline, and
publishes episode history, policy, Q-table, trajectory, report and figure.

## Running it

```bash
uv run gridalyn project run projects/rl_voltage_control_lightsim
uv run gridalyn project status projects/rl_voltage_control_lightsim --check-artifacts
```

| Stage | Purpose |
| --- | --- |
| `prepare_workspace` | Creates output folders. |
| `build_rl_feeder` | Builds a 10-bus radial feeder through `RadialFeederSpec`, initializes the LightSim adapter, and writes feeder assets/report/figure. |
| `train_rl_voltage_agent` | Calls the tabular voltage-control trainer against `VoltageControlEnvironment`, evaluates the greedy policy, and writes learning/control artifacts. |
| `export_twin_network_model` | Exports the resulting network model to the twin. |

## What it produces

| Artifact | What it holds |
| --- | --- |
| `outputs/data/training_episodes.csv` | Episode reward history |
| `outputs/data/policy_evaluation_trajectory.csv` | Greedy policy trajectory |
| `outputs/operations/q_table.csv` | Learned tabular Q-values |
| `outputs/operations/learned_policy.csv` | Best action by discrete state |
| `outputs/reports/rl_voltage_control_report.json` | Learning and voltage metrics |
| `outputs/figures/rl_voltage_control.png` | Voltage, action and reward summary |

Plus the feeder stage's own report and figure, and the run manifest.

## How it is verified

The study's own check is the comparison the training stage performs: the
learned policy is evaluated against an uncontrolled baseline over the same
24-step load/PV profile, so a policy that learned nothing is visible in the
report rather than hidden by it. Around that,
`gridalyn project status --check-artifacts` confirms the artifacts appeared,
`gridalyn project regression` compares against
`baselines/results_baseline.json`, and the study runs in CI as one of the six
governed fixtures.

## Scope and limits

This is not a production controller. The state space is discrete — a voltage
bin at the controlled bus, a state-of-charge bin, and the time-step index — and
the action space is three points:

```text
[-0.12, 0.0, 0.12] MW
```

Negative charges the battery, positive discharges. The reward penalises
voltage-band violation, deviation from nominal, and battery movement. Nothing
here is tuned for performance; it is sized to stay inspectable.

Note that `lightsim2grid` is an optional capability, not a base dependency. A
checkout without it cannot run this study.

## Where this sits

The boundary is the point: workflow wiring and the concrete feeder, DER
contract and deterministic 24-step profiles stay in `project.yaml`, while the
reusable network, environment and training pieces come from the SDK.

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

A new learning-control study should reuse the same feeder, DER and environment
contracts while swapping the controller for MPC, safe RL or a rules-based
policy. See [Simulation](../../docs/components/simulation.md) for the
environment and policy registries that make that swap explicit.
