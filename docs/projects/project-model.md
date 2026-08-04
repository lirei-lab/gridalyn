# Project Model

A Gridalyn project is a reproducible unit of work. It declares the problem,
scenarios, experiments, inputs, workflow stages, expected artifacts, reports,
figures, manifests, and regression checks.

## Project Structure

```text
projects/<project_name>/
  project.yaml
  workflow.yaml
  scripts/
  outputs/
    data/
    figures/
    json/
    manifests/
    operations/
    reports/
```

## Create A Project

Use the `grid-study` template when creating a new runnable study workspace:

```bash
uv run gridalyn project init projects/my_case --name my_case --template grid-study
```

The template creates:

- `project.yaml`;
- `workflow.yaml`;
- `scripts/write_summary_report.py`;
- `inputs/`;
- `outputs/data`;
- `outputs/figures`;
- `outputs/cache`;
- `outputs/manifests`;
- `outputs/operations`;
- `outputs/reports`.

It can run immediately:

```bash
uv run gridalyn project run projects/my_case
uv run gridalyn project status projects/my_case --check-artifacts
```

The default `minimal` template is still available for users who want only the
bare project contract:

```bash
uv run gridalyn project init projects/my_minimal_case --template minimal
```

## Responsibilities

| File or folder | Responsibility |
| --- | --- |
| `project.yaml` | Project identity, problem contract, scenarios, experiments, path policy, inputs, outputs, and validation expectations. |
| `workflow.yaml` | Ordered workflow stages and command execution contract. |
| `scripts/` | Project orchestration only; reusable logic belongs in `gridalyn/`. |
| `outputs/data/` | Project-local Parquet/CSV/derived data. |
| `outputs/reports/` | Stable JSON reports. |
| `outputs/figures/` | Figures generated from project data. |
| `outputs/cache/` | Project-local caches, including non-source runtime caches such as Matplotlib. |
| `outputs/operations/` | Dispatch instructions, operation runs, operational catalogs, and settlement-ready artifacts. |
| `outputs/manifests/` | Run manifests and artifact inventories. |

## Declarative Model Inputs

Concrete demo parameters belong in `project.yaml`, not in SDK modules named
after a demo. For compact synthetic studies, declare feeder, DER, prosumer, or
profile values under `spec.inputs`, then load them through
`gridalyn.projects` model-input helpers such as `load_radial_feeder_spec`,
`load_prosumer_assets`, `load_der_dispatch_assets`, and
`load_voltage_control_der_spec`.

This keeps project data reproducible and inspectable while preserving the SDK
as reusable contracts, validators, builders, simulators, and operations.

## Validation Ladder

A healthy project should pass three increasingly strict checks:

```bash
uv run gridalyn project validate projects/<project> --check-artifacts
uv run gridalyn project status projects/<project> --check-artifacts
uv run gridalyn project sense-check projects/<project>
```

`validate` and `status` check the project contract. `sense-check` verifies that
the generated values make sense for the objective of the project, such as
improved voltage after control, positive settlement, or one synthetic load per
generated building.

Projects can declare lightweight sense checks directly in `project.yaml`.
Declarative checks make new demos extensible without adding project-specific
Python code:

```yaml
spec:
  validation:
    senseChecks:
      - id: voltage_floor
        report: outputs/reports/project_summary.json
        field: summary.min_voltage_pu
        min: 0.95
      - id: powerflow_converged
        report: outputs/reports/project_summary.json
        field: summary.converged
        equals: true
```

Each rule reads a JSON report, resolves the dotted field path, and supports
`equals`, `min`, `max`, `gt`, `gte`, `lt`, and `lte`.

## Problem, Scenarios, And Experiments

Every public project must declare `spec.problem`. This keeps the platform from
mixing responsibilities between assets, simulators, digital twins, and demo
scripts.

The contract has three levels:

| Level | Responsibility |
| --- | --- |
| `problem` | The reusable study statement: dataset, environment, objective, and model. |
| `problem.scenarios` | Stable operating cases such as baseline, EV penetration level, DER condition, market stress case, or train/evaluate split. |
| `experiments` | Runs or sweeps that reference one or more declared scenarios, expected metrics, model, and proof artifacts. |

The contract follows model-centered experiment discipline without introducing
explicit spaces yet. Keep state/action/input/output assumptions in model docs or
reports until multiple workflows need the same formal abstraction.

For the detailed schema and examples, see
[Project Problem Contract](problem-contract.md).

## Public Example Projects

Gridalyn includes several public executable projects. They demonstrate the same
contract at different levels of complexity, but they do not define the platform
boundary. Reusable behavior belongs in `gridalyn/`; projects should stay thin
and declarative.

For power-flow demos, project scripts should call the native simulation helpers
for pandapower tables, voltage figures, standard scenario execution, and
canonical reports. For market demos, clearing and dispatch belong in
`gridalyn.operations`; the project should pin local parameters and persist the
declared outputs.

Use the examples as a progression:

| Project | Platform contract it demonstrates |
| --- | --- |
| [Minimal Grid Project](https://github.com/lirei-lab/gridalyn/tree/main/projects/minimal_grid_project) | Smallest project contract, report, figure, and sense-check loop. |
| [IEEE 33-Bus Demo](https://github.com/lirei-lab/gridalyn/tree/main/projects/ieee_33_bus_demo) | Benchmark feeder workflow with deterministic scenario outputs. |
| [Synthetic GeoJSON Feeder](https://github.com/lirei-lab/gridalyn/tree/main/projects/synthetic_geojson_feeder) | GeoJSON-to-network generation with validation artifacts. |
| [Prosumer Battery Market Demo](https://github.com/lirei-lab/gridalyn/tree/main/projects/prosumer_battery_market) | Asset modeling, market clearing, dispatch, and feeder verification. |
| [DER Voltage Optimization Demo](https://github.com/lirei-lab/gridalyn/tree/main/projects/der_voltage_optimization) | Optimization setpoints verified against AC power flow. |
| [RL Voltage Control With LightSim2Grid](https://github.com/lirei-lab/gridalyn/tree/main/projects/rl_voltage_control_lightsim) | Learning-control environment over reusable modeling assets. |

See [Workflow YAML](../workflows/workflow-yaml-reference.md) and
[Project Template Guide](template-guide.md).
