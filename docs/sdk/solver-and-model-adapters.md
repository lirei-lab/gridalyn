# Solver And Model Adapters

Gridalyn should treat solvers and model generators as replaceable adapters, not
as the identity of the platform. The stable platform contract is:

```text
NetworkModelRepository -> SolverAdapter -> SimulationResult -> Report
```

This lets projects consume the same governed artifacts while choosing the
engine that matches the study.

## Current Adapter Surface

| Capability | Current Gridalyn path | Role |
| --- | --- | --- |
| Network repository | `gridalyn.twin.NetworkModelRepository` | Reads canonical Parquet network artifacts. |
| Synthetic network builder | `gridalyn.assets.build_synthetic_network_from_geojson` | Builds a graph, pandapower model, validation report, and cache bundle. |
| Pandapower builder | `gridalyn.simulation.PandapowerGridBuilder` | Converts `PowerGridGraph` topology into pandapower networks. |
| LightSim adapter | `gridalyn.simulation.LightSimPowerflowAdapter` | Runs faster power-flow checks when LightSim2Grid is installed. |
| Voltage-control environment | `gridalyn.simulation.VoltageControlEnvironment` | Provides a small learning-control surface over reusable feeder assets. |
| Operations facade | `gridalyn.operations` | Converts providers, constraints, dispatch, settlement, and KPIs into governed outputs. |

## Design Rule

Adapters should be thin. They translate between Gridalyn artifacts and an
external model or solver, then return stable Gridalyn outputs. They should not
own project assumptions, write hidden files, or infer scenario meaning from a
single demo.

## Near-Term Adapter Roadmap

| Adapter | Why it matters | Release posture |
| --- | --- | --- |
| `PandapowerAdapter` | Baseline Python power-flow and OPF integration. | Current default. |
| `LightSimPowerflowAdapter` | Faster evaluation path for compatible pandapower networks. | Optional `sim` capability. |
| `OpenDSSDirectAdapter` | Independent distribution-system solver validation path. | Candidate v0.2 adapter. |
| `PowerModelsDistributionAdapter` | Unbalanced and optimization-oriented distribution formulations. | Candidate research adapter. |
| `CimParquetAdapter` | Utility model ingestion path through canonical tables. | Current import/export direction. |

## Cross-Solver Validation

Before claiming operational fidelity, a project should separate three checks:

1. **Contract validation:** project YAML, workflow YAML, required artifacts,
   reports, and manifests exist.
2. **Sense checks:** output values match the project objective.
3. **Cross-solver checks:** independent engines agree within declared
   tolerances for voltage, loading, losses, convergence, or dispatch effects.

Gridalyn v0.1 focuses on the first two. The public roadmap should make the
third explicit so users understand that solver parity is a deliberate platform
boundary, not an accidental omission.
