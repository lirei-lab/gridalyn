# Solver And Model Adapters

Gridalyn should treat solvers and model generators as replaceable adapters, not
as the identity of the platform. The stable platform contract is:

```text
NetworkModelRepository -> PowerFlowBackend -> NetworkObservation -> Report
```

This lets projects consume the same governed artifacts while choosing the
engine that matches the study. Since the network control framework landed
(2026-08-11), the solver seam is a registry rather than a hand-picked class:
every power-flow call in the SDK resolves a backend by explicit ID, and the
resolved backend is recorded in the run manifest under
`provenance.powerflow_backend`. See
[Platform Layer Model](../platform/platform-layer-model.md#network-control-registries-2026-08-10).

## Current Adapter Surface

| Capability | Current Gridalyn path | Role |
| --- | --- | --- |
| Network repository | `gridalyn.twin.NetworkModelRepository` | Reads canonical Parquet network artifacts. |
| Synthetic network builder | `gridalyn.simulation.build_synthetic_network_from_geojson` | Builds a graph, pandapower model, validation report, and cache bundle. |
| Pandapower builder | `gridalyn.simulation.PandapowerGridBuilder` | Converts Gridalyn topology bundles into pandapower networks. |
| **Power-flow backend registry** | `gridalyn.simulation.resolve_powerflow_backend` | Resolves the solver by explicit ID (`pandapower_native` default, `lightsim2grid`). The single place a power flow is solved. |
| Observation contract | `gridalyn.twin.observation.observe_network` | One definition of what a solved network shows, independent of which backend solved it. It was moved down to the twin: what a network shows is a property of the network, not of the solver. The `gridalyn.simulation` path still resolves, via a deprecation shim. |
| Surrogate registry | `gridalyn.simulation.resolve_surrogate` | Resolves a surrogate by explicit ID; every registered surrogate carries a stated error bound. |
| Policy registry | `gridalyn.simulation.policies.default_policy_registry` | Resolves a control policy by explicit ID (tabular RL, sensitivity dispatch). |
| Voltage-control environment | `gridalyn.simulation.VoltageControlEnvironment` | Composes a backend, an observation, and a policy into a learning-control surface. |
| Operations facade | `gridalyn.operations` | Converts providers, constraints, dispatch, settlement, and KPIs into governed outputs. |

`gridalyn.simulation.LightSimPowerflowAdapter` remains exported for backwards
compatibility but is **no longer used inside the SDK** — it has zero
construction sites, and it predates both the backend registry and
`provenance.powerflow_backend`, so a run driven through it records no engine
provenance. Use `resolve_powerflow_backend("lightsim2grid")` instead.

## Design Rule

Adapters should be thin. They translate between Gridalyn artifacts and an
external model or solver, then return stable Gridalyn outputs. They should not
own project assumptions, write hidden files, or infer scenario meaning from a
single demo.

## Near-Term Adapter Roadmap

| Adapter | Why it matters | Release posture |
| --- | --- | --- |
| `pandapower_native` | Baseline Python power-flow integration. | Registered, current default. |
| `lightsim2grid` | Faster evaluation path for compatible pandapower networks. | Registered; requires the optional `sim` capability. |
| `OpenDSSDirectAdapter` | Independent distribution-system solver validation path. | Candidate v0.2 backend. |
| `PowerModelsDistributionAdapter` | Unbalanced and optimization-oriented distribution formulations. | Candidate research backend. |
| `CimParquetAdapter` | Utility model ingestion path through canonical tables. | Current import/export direction. |

The first two are backend IDs registered in
`gridalyn.simulation.backends.registry`, not class names to import — they
resolve through `resolve_powerflow_backend(<id>)`. The remaining three are
prospective and not implemented. Adding a backend means registering it
explicitly in `default_powerflow_backend_registry()`; there is deliberately no
`entry_points` discovery, because an ambient plugin would change a solved
result without appearing in the run manifest.

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
