# Project Problem Contract

Every Gridalyn project must declare the problem it solves before it declares
workflow mechanics. This keeps demos, examples, and operations studies aligned
around the same vocabulary.

Gridalyn borrows the useful discipline of model-centered experiment frameworks:
declare the dataset, environment, objective, model, scenarios, experiments, and
metrics before writing workflow scripts. It does not expose explicit state,
action, input, or output spaces in the public project contract yet; those should
remain model documentation until they are needed by multiple workflows.

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
      type: simulation_model
      name: gridalyn_ieee_33_bus_benchmark
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
      model: gridalyn_ieee_33_bus_benchmark
      artifacts:
        - outputs/reports/ieee33_powerflow_report.json
```

| Field | Meaning |
| --- | --- |
| `type` | Stable category of study, such as `powerflow_validation`, `local_market_dispatch`, or `learning_voltage_control`. |
| `dataset` | Named source data or generated dataset used by the project. |
| `environment` | Execution environment or simulator context. |
| `objective` | One-sentence reason the project exists. |
| `model` | Primary asset, forecast, simulation, optimization, control, market, operations, or workflow model. |
| `scenarios` | Stable operating cases available to workflow stages and reports. |
| `experiments` | Runs, sweeps, or comparisons that reference declared scenarios, metrics, model, and proof artifacts. |

## Model Type Vocabulary

Use a small model vocabulary so readers know what role a model plays:

| Type | Use when |
| --- | --- |
| `asset_model` | The project creates or validates reusable asset, feeder, building, DER, EVSE, or load models. |
| `forecast_model` | The project produces forecast or baseline trajectories. |
| `simulation_model` | The project runs physical or replay simulation. |
| `optimization_model` | The project solves a constrained optimization problem. |
| `control_model` | The project evaluates a controller or learning policy. |
| `market_model` | The project clears or evaluates a market mechanism. |
| `operations_model` | The project combines providers, constraints, dispatch, settlement, and verification. |
| `workflow_model` | The project is primarily a template or workflow contract demonstration. |

Do not add explicit `spaces` to public project contracts for now. If a model has
state, action, input, or output assumptions, document them in the model docs or
report metadata and promote them only after the abstraction has multiple users.

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
- every problem uses a known `model.type`;
- scenario IDs are unique;
- experiment IDs are unique;
- every experiment references a known scenario.

Run:

```bash
uv run gridalyn project validate projects/<project>
uv run gridalyn project verify projects/<project>
```
