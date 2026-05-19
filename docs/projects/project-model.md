# Project Model

A Gridalyn project is a reproducible unit of work. It declares inputs,
configuration, workflow stages, expected artifacts, reports, figures, manifests,
and regression checks.

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
| `project.yaml` | Project identity, path policy, inputs, outputs, and validation expectations. |
| `workflow.yaml` | Ordered workflow stages and command execution contract. |
| `scripts/` | Project orchestration only; reusable logic belongs in `gridalyn/`. |
| `outputs/data/` | Project-local Parquet/CSV/derived data. |
| `outputs/reports/` | Stable JSON reports. |
| `outputs/figures/` | Figures generated from project data. |
| `outputs/operations/` | Dispatch instructions, operation runs, operational catalogs, and settlement-ready artifacts. |
| `outputs/manifests/` | Run manifests and artifact inventories. |

## Validation Ladder

A healthy project should pass three increasingly strict checks:

```bash
uv run gridalyn project validate projects/<project> --check-artifacts
uv run gridalyn project status projects/<project> --check-artifacts
uv run gridalyn project sense-check projects/<project>
```

`validate` and `status` check the project contract. `sense-check` verifies that
the generated values make sense for the purpose of the demo, such as improved
voltage after control, positive settlement, or one synthetic load per generated
building.

## Demo Projects

Gridalyn includes several public demo projects. They are examples of the same
project contract at different levels of complexity, not study-specific
reference artifacts.

For the smallest project contract example, use:

```text
projects/minimal_grid_project/
```

It builds a five-bus radial feeder, runs one pandapower power flow, and writes
one report and one figure. See [Minimal Grid Project](minimal-grid-project.md).

For the smallest benchmark-feeder smoke test, use:

```text
projects/ieee_33_bus_demo/
```

It runs a pandapower 33-bus distribution benchmark and writes CSV tables, a
contractual JSON report, and a voltage profile figure. See
[IEEE 33-Bus Demo](ieee-33-demo.md).

For the geospatial network-generation path, use:

```text
projects/synthetic_geojson_feeder/
```

It generates a tiny building-footprint GeoJSON dataset, converts it into a
synthetic LV/MV/HV feeder, runs pandapower, and writes network validation
artifacts. See [Synthetic GeoJSON Feeder](synthetic-geojson-feeder.md).

For a compact operations and market example, use:

```text
projects/prosumer_battery_market/
```

It builds a small synthetic feeder, places five PV+battery prosumers, clears a
real-time battery-dispatch market, and verifies the post-market feeder state.
See [Prosumer Battery Market Demo](prosumer-battery-market.md).

For a compact optimization and verification example, use:

```text
projects/der_voltage_optimization/
```

It builds a synthetic feeder, derives voltage sensitivities, solves a
voltage-constrained DER dispatch with `cvxpy`, and verifies the optimized
setpoints with pandapower. See
[DER Voltage Optimization Demo](der-voltage-optimization.md).

For a compact learning-control example, use:

```text
projects/rl_voltage_control_lightsim/
```

It trains a tabular Q-learning battery controller on a 10-bus synthetic feeder
using `lightsim2grid` as the fast simulation backend. See
[RL Voltage Control With LightSim2Grid](rl-voltage-control-lightsim.md).

For the larger end-to-end flexibility operations workflow, use:

```text
projects/flexibility_cls/
```

It regenerates the topology cache, stochastic load scenarios, CLS market
clearing, real-time dispatch, settlement, operations artifacts, reports, and
figures. See [Flexibility CLS](../workflows/flexibility-cls.md).

See [Workflow YAML](../workflows/workflow-yaml-reference.md) and
[Project Template Guide](template-guide.md).
