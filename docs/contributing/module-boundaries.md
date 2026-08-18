# Module Boundaries

Gridalyn uses seven public SDK modules. Their job is to keep project workflows,
examples, applications, and future utility integrations from depending on a
single demo's internal structure.

## Ownership Rules

| Module | Owns | Does not own |
| --- | --- | --- |
| `gridalyn.foundation` | Workspace paths, IDs, manifests, reports, validation, artifact policy. | Grid topology, assets, solver behavior, project assumptions. |
| `gridalyn.twin` | Canonical network snapshots, topology, source adapters, semantic graph, graph/database adapters. | Synthetic load generation, Monte Carlo execution, market decisions. |
| `gridalyn.assets` | Buildings, devices, DER, EVSE, batteries, prosumers, archetypes, synthetic asset and load-profile generation. | Power-flow execution, dashboard publication, settlement. |
| `gridalyn.simulation` | Solver adapters, power-flow execution, Monte Carlo orchestration, physical validation. | Domain meaning of assets, dashboard publication, project-specific scenario policy. |
| `gridalyn.operations` | Providers, constraints, clearing, dispatch, settlement, operational KPIs. | Building canonical network models or generating base asset tables. |
| `gridalyn.projects` | Project and workflow manifests, project runners, regression and sense checks. | Reusable domain logic. |
| `gridalyn.interfaces` | CLI entrypoints, report/dashboard-facing surfaces, visualization adapters. | Core modeling or simulation assumptions. |

## Dependency Direction

Use this direction when deciding where new code belongs:

```text
projects   -> foundation + twin + assets + simulation + operations + interfaces
interfaces -> foundation + twin + projects
operations -> foundation + assets + simulation
simulation -> foundation + twin + assets
assets     -> foundation + twin
twin       -> foundation
foundation -> standard library and external primitives only
```

This is the graph the code actually forms, measured by walking every import in
`gridalyn/`. Two entries used to be stated more narrowly than reality: `assets`
does import `twin` (`assets/modeling/artifacts.py`), and `operations` imports
`assets` and `simulation` while never importing `twin` at all.

What is *enforced* is narrower still: `tests/test_project_hygiene.py`
`test_core_layers_do_not_import_orchestration_layers` bans upward imports only —
no core layer may import `projects` or `interfaces`, and `foundation` may import
no layer. The sideways edges above are description, not rule.

The important rule is that new reusable code should move toward this graph.
Project scripts may compose all SDK modules, but SDK modules should not import
project runtime logic.
Workspace-level validation may inspect project contracts through a late-bound
project API, but `foundation` must not become a public facade for projects,
operations, simulation, or assets.

Runtime source should target the native public contracts directly. When a path,
format, or workflow alias is retired, migrate active callers to the owning
module instead of keeping parallel implementations.

## Placement Examples

| Need | Put it in |
| --- | --- |
| GeoJSON footprint parsing | `gridalyn.twin.adapters` or `gridalyn.twin.geoprocess` |
| Building/device/DER entities | `gridalyn.assets.modeling` |
| Transformer thermal model primitives | `gridalyn.assets.modeling` |
| Synthetic heating/background load profiles | `gridalyn.assets.datagen` |
| Synthetic weather-to-thermal-limit generation | `gridalyn.assets.datagen` |
| GeoJSON-to-pandapower network construction | `gridalyn.simulation.simulators.powerflow` |
| Pandapower or LightSim2Grid execution | `gridalyn.simulation` |
| Dashboard catalogs and visualization-facing surfaces | `gridalyn.interfaces` |
| Flexibility provider selection | `gridalyn.operations` |
| Workflow stage that pins paths and parameters | `projects/<project>/scripts/` |

## Boundary Decisions

- Synthetic building, EV, and load-profile generation is native to
  `gridalyn.assets.datagen`.
- Transformer thermal behavior is native to `gridalyn.assets.modeling`; datagen
  may use it to build synthetic stress-test assumptions. Modeling modules must
  not import datagen, solvers, operations, or projects.
- Simulation produces solver results; project workflows or digital-twin instance
  contracts decide where those results are written and how dashboards consume
  them. Dashboard publication belongs in catalog/report contracts, not
  simulation exporters.
- `gridalyn.assets.datagen.MVNetwork` is an aggregate synthetic stress-test
  model with explicit configuration, not a hidden import-time binding to one
  project config file.
- Operations dispatchers consume a network-constraint protocol. Project code may
  pass an `MVNetwork`, but operations modules should not import datagen
  directly.
- Market offers and settlement use the native cap contract:
  `p_ref_kw`, `p_cap_kw`, `delta_p_kw`, and explicit settlement
  `p_cap_limit_kw`. Baseline-only offer shapes are not accepted in the
  public runtime.
- The root `gridalyn` CLI delegates domain help to the owning parser, so
  commands such as `gridalyn project --help` list the project subcommands rather
  than a placeholder wrapper.

## Review Checklist

Before adding or moving a module, ask:

- Is this entity/model definition, or is it a solver execution?
- Does it create canonical twin state, or consume it?
- Does it encode a project assumption that belongs in `projects/<project>`?
- Can another project reuse it without importing a sibling project's scripts?
- Can the generated output be reproduced through a declared workflow?
