# Project Problem Contract

Every Gridalyn project must declare the problem it solves before it declares
workflow mechanics. This keeps demos, examples, and operations studies aligned
around the same vocabulary.

## Why It Exists

`project.yaml` is not only a list of paths. It is the public contract for a
reproducible study:

- `problem` says what is being studied;
- `scenarios` say which operating cases are in scope;
- `experiments` say which comparable runs or sweeps should be evaluated;
- `workflow.yaml` says how the declared contract is executed;
- `validation` says which artifacts prove the project ran correctly.

## Required Fields

```yaml
spec:
  problem:
    type: benchmark_powerflow_scenarios
    dataset: ieee_33_bus_benchmark
    environment: gridalyn_powerflow
    objective: Compare deterministic operating scenarios on a known feeder.
    model:
      type: simulator
      name: gridalyn_ieee_33_bus_benchmark
    spaces:
      state: feeder_load_generation_condition
      action: scenario_overlay
      output: voltage_and_loading_metrics
    scenarios:
      - id: baseline
        role: benchmark_base_case
        description: Original feeder condition.
  experiments:
    - id: deterministic_scenario_comparison
      scenario: baseline
      objective: Validate voltage and loading metrics.
      metrics:
        - min_voltage_pu
```

| Field | Meaning |
| --- | --- |
| `type` | Stable category of study, such as `powerflow_validation`, `local_market_dispatch`, or `learning_voltage_control`. |
| `dataset` | Named source data or generated dataset used by the project. |
| `environment` | Execution environment or simulator context. |
| `objective` | One-sentence reason the project exists. |
| `model` | Primary model, simulator, optimizer, agent, or operations pipeline. |
| `spaces` | Named state, action, observation, or output contracts. |
| `scenarios` | Stable operating cases available to workflow stages and reports. |
| `experiments` | Runs, sweeps, or comparisons that reference declared scenarios. |

## Scenario Rules

Scenarios are not workflow stages and not output folders. They are named
operating cases. A scenario can represent an adoption level, DER condition,
market condition, stress case, training split, or validation case.

Use a scenario when the same problem could be run under a different condition.
Use an experiment when you want to compare one or more scenarios with a shared
objective and metrics.

## Validation

The project validator enforces that:

- every project declares `spec.problem`;
- every problem has at least one scenario;
- scenario IDs are unique;
- experiment IDs are unique;
- every experiment references a known scenario.

Run:

```bash
uv run gridalyn project validate projects/<project>
uv run gridalyn project verify projects/<project>
```
