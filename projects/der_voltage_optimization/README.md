# DER Voltage Optimization

This project demonstrates a small utility-planning workflow that mixes convex
optimization with physical power-flow verification.

The workflow builds a synthetic 16-bus radial feeder with high downstream PV,
declares DER capability through Gridalyn asset models, runs Gridalyn's
voltage-constrained DER dispatch operation, and then verifies the optimized
setpoints with an AC power-flow snapshot.

## Run

```bash
uv run gridalyn project run projects/der_voltage_optimization
uv run gridalyn project status projects/der_voltage_optimization --check-artifacts
```

## Outputs

- `outputs/data/der_assets.csv`: PV and battery assets.
- `outputs/data/voltage_sensitivity_matrix.csv`: finite-difference voltage sensitivity used by the convex model.
- `outputs/operations/der_dispatch.csv`: optimized PV dispatch, curtailment, and battery charging.
- `outputs/data/pandapower_verification.csv`: before/after AC power-flow voltages.
- `outputs/reports/der_voltage_optimization_report.json`: canonical optimization report.
- `outputs/figures/der_voltage_optimization.png`: voltage comparison and DER setpoints.

## Scope

This is not a replacement for an AC OPF. It is a small reproducible example of
how Gridalyn can combine optimization models, asset tables, and physical
verification in one governed project workflow.
