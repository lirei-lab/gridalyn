# DER Voltage Optimization Demo

`projects/der_voltage_optimization` is a compact planning and operations demo
that combines convex optimization with physical power-flow verification.

## Why This Demo Exists

Gridalyn should support more than scenario replay. This project shows how a
workflow can:

- declare the concrete DER feeder and assets in `project.yaml`;
- load that contract through Gridalyn project model-input helpers;
- derive a linearized voltage-sensitivity model through the SDK operation;
- solve a voltage-constrained DER dispatch problem through Gridalyn operations;
- verify the optimized setpoints with an AC pandapower power flow;
- publish reports, figures, and operation tables.

It is a useful pattern for hosting-capacity studies, DERMS prototypes, planner
assistants, and future optimization-backed applications.

## Run It

```bash
uv run gridalyn project run projects/der_voltage_optimization
uv run gridalyn project status projects/der_voltage_optimization --check-artifacts
```

Expected generated artifacts:

```text
projects/der_voltage_optimization/outputs/data/buses.csv
projects/der_voltage_optimization/outputs/data/lines.csv
projects/der_voltage_optimization/outputs/data/loads.csv
projects/der_voltage_optimization/outputs/data/der_assets.csv
projects/der_voltage_optimization/outputs/data/voltage_sensitivity_matrix.csv
projects/der_voltage_optimization/outputs/data/pandapower_verification.csv
projects/der_voltage_optimization/outputs/operations/der_dispatch.csv
projects/der_voltage_optimization/outputs/reports/der_feeder_report.json
projects/der_voltage_optimization/outputs/reports/der_voltage_optimization_report.json
projects/der_voltage_optimization/outputs/figures/der_feeder_voltage_profile.png
projects/der_voltage_optimization/outputs/figures/der_voltage_optimization.png
projects/der_voltage_optimization/outputs/manifests/project_run_manifest.json
```

## Workflow

| Stage | Purpose |
| --- | --- |
| `prepare_workspace` | Creates output folders. |
| `build_der_feeder` | Loads the 16-bus DER feeder contract from `project.yaml`, applies `DERDispatchAsset` PV setpoints through Gridalyn simulation helpers, and writes feeder/DER artifacts. |
| `solve_voltage_optimization` | Calls the Gridalyn DER voltage-dispatch operation, persists sensitivity, dispatch, verification, report, and figure artifacts. |

## Optimization Model

The optimization is a linearized voltage-constrained DER dispatch:

```text
minimize   PV curtailment + small battery charging penalty + voltage deviation penalty
subject to 0 <= PV dispatch <= PV available
           0 <= battery charge <= battery power
           0.95 <= V_base + S * (PV dispatch - battery charge) <= 1.05
```

`S` is computed from finite-difference perturbations in the Gridalyn operation.
The optimized setpoints are then applied back to an AC model for verification.
This keeps the demo simple while preserving the essential platform pattern:

```text
asset model -> sensitivity model -> convex optimizer -> AC verification -> report
```

This is not a full AC OPF. It is a transparent and reproducible bridge between
fast convex planning logic and physical validation.
