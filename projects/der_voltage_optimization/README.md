# DER Voltage Optimization

A compact planning-and-operations study that combines convex optimization with
physical power-flow verification. It builds a synthetic 16-bus radial feeder
with high downstream PV, declares DER capability through Gridalyn asset models,
runs the voltage-constrained DER dispatch operation, and then checks the
optimized setpoints against an AC power-flow snapshot.

## What this study asks

Whether a fast convex decision survives contact with the physics it
approximates — and it is the platform's clearest example of that loop, because
both halves are visible in one short workflow:

```text
asset model -> sensitivity model -> convex optimizer -> AC verification -> report
```

It exists to show that a workflow can do more than replay a scenario. Within
one governed project it declares the feeder and assets in `project.yaml`, loads
that contract through the typed model-input helpers, derives a linearized
voltage-sensitivity model, solves a constrained dispatch, verifies the result
in pandapower, and publishes reports, figures and operation tables. That is a
useful pattern for hosting-capacity studies, DERMS prototypes and planner
assistants.

## Running it

```bash
uv run gridalyn project run projects/der_voltage_optimization
uv run gridalyn project status projects/der_voltage_optimization --check-artifacts
```

| Stage | Purpose |
| --- | --- |
| `prepare_workspace` | Creates output folders. |
| `build_der_feeder` | Loads the 16-bus DER feeder contract from `project.yaml`, applies `DERDispatchAsset` PV setpoints through the simulation helpers, and writes feeder/DER artifacts. |
| `run_voltage_optimization` | Calls the DER voltage-dispatch operation, then persists sensitivity, dispatch, verification, report and figure artifacts. |
| `export_twin_network_model` | Exports the resulting network model back to the twin. |

## What it produces

| Artifact | What it holds |
| --- | --- |
| `outputs/data/der_assets.csv` | PV and battery assets |
| `outputs/data/voltage_sensitivity_matrix.csv` | Finite-difference voltage sensitivity the convex model decides on |
| `outputs/operations/der_dispatch.csv` | Optimized PV dispatch, curtailment and battery charging |
| `outputs/data/pandapower_verification.csv` | Before/after AC power-flow voltages |
| `outputs/reports/der_voltage_optimization_report.json` | The canonical optimization report |
| `outputs/figures/der_voltage_optimization.png` | Voltage comparison and DER setpoints |

Alongside these the feeder stages write `buses.csv`, `lines.csv`, `loads.csv`,
`der_feeder_report.json`, `der_feeder_voltage_profile.png` and the run
manifest.

## How it is verified

Three layers, and they answer different questions. The AC power flow in
`pandapower_verification.csv` asks whether the convex decision holds
physically — it is the study's own subject, not a formality.
`gridalyn project status --check-artifacts` asks whether every declared
artifact appeared. `gridalyn project regression` asks whether the numbers moved
against `baselines/results_baseline.json`. The study runs end to end in CI as
one of the six governed fixtures.

## Scope and limits

This is not a replacement for an AC OPF. The optimization is a linearized,
voltage-constrained DER dispatch:

```text
minimize   PV curtailment + small battery charging penalty + voltage deviation penalty
subject to 0 <= PV dispatch <= PV available
           0 <= battery charge <= battery power
           0.95 <= V_base + S * (PV dispatch - battery charge) <= 1.05
```

`S` comes from finite-difference perturbations inside the operation. The
linearization is what makes the problem convex and the demo transparent; it is
also why the AC verification step is not optional.

## Where this sits

It builds on [Assets](../../docs/components/assets.md) for the DER specs and on
[Operations](../../docs/components/operations.md) for the dispatch itself, and
returns its result to the twin through `export_twin_network_model`. For the
same convex-decision-checked-against-physics pattern applied to a surrogate
rather than a dispatch, see the error-bound contract in
[Simulation](../../docs/components/simulation.md).
