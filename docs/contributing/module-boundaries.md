# Architecture Rules

This page says where new code goes and which tests hold it there. The seven
layers, and the order they import in, are described once in
[The Platform, In One Pass](../components/overview.md); this page assumes that
stack and adds the rules a contributor follows inside it.

## The rules

1. **Imports point down.** A module may import its own layer and any layer
   below it in `foundation → twin → assets → simulation → operations → projects
   → interfaces`. Skipping layers downward is legal (`interfaces` may import
   `twin` directly); an upward import is not.
2. **The SDK does not know about individual studies.** Reusable behaviour lives
   in `gridalyn/`. Nothing under `gridalyn/` imports from `projects/`, names a
   concrete `projects/<name>/` path, or edits `sys.path`.
3. **Study scripts stay thin.** A script under `projects/<name>/scripts/` loads
   its typed inputs, calls the SDK, and writes the outputs its project
   declares. It does not define reusable asset models, solver builders, market
   engines or reporting frameworks, read another study's paths, or depend on
   `examples/`. When two studies need the same function, move it into the
   owning layer instead of copying it.
4. **Optional dependencies stay optional.** Importing any `gridalyn`
   sub-package must not load `lightsim2grid`, `cvxpy` or `osmnx`. How to
   satisfy that is in [Conventions](conventions.md#lazy-exports).
5. **Platform reports go through the report contract.** A stage that reports on
   its own run writes a platform report through `script.write_report(...)`,
   never hand-built JSON; see
   [Reports And Figures](../guides/reports-and-figures.md).

## What enforces them

Each rule is a test in the default `pytest` run, so breaking one fails the
`test` job in CI.

| Rule | Test | What it catches |
| --- | --- | --- |
| 1 | `tests/test_layer_direction.py` | Any import of a higher layer under `gridalyn/`, read from `import` statements (relative ones resolved), string arguments to `import_module(...)` and `__import__(...)`, and the targets of every `_LAZY_EXPORTS` map, so an upward edge cannot hide in a lazy export. |
| 1 | `tests/test_asset_modeling_boundaries.py`, `tests/test_operations_boundaries.py` | Narrower scans: `gridalyn/assets/modeling` importing datagen, solvers, operations or projects; `gridalyn/operations` importing upward or reintroducing retired packages. |
| 1 | `test_core_layers_do_not_import_orchestration_layers` in `tests/test_project_hygiene.py` | A core layer importing `projects` or `interfaces`. |
| 2 | `test_gridalyn_package_does_not_depend_on_projects` in `tests/test_project_hygiene.py` | A concrete `projects/<name>/` path, an import from `projects.`, or a `sys.path.insert` under `gridalyn/`. |
| 3 | `tests/test_project_compliance_boundaries.py` | A study script importing an internal package (such as `simulators`) instead of the public facade, or importing `pandapower`, `lightsim2grid` or `geopandas` at module scope. |
| 4 | `tests/test_import_hygiene.py` | A sub-package whose import puts a truly optional module in `sys.modules`. |
| 5 | `tests/test_report_contract.py` | A direct JSON write that has not been classified, and any write classified as a hand-built platform report. |

## Where things go

| Layer | Owns | Does not own |
| --- | --- | --- |
| `gridalyn.foundation` | Workspace paths, IDs, manifests, reports, validation, artifact policy. | Grid topology, assets, solver behaviour, study assumptions. |
| `gridalyn.twin` | Canonical network snapshots, topology, source adapters, semantic graph, graph/database adapters. | Synthetic load generation, Monte Carlo execution, market decisions. |
| `gridalyn.assets` | Buildings, devices, DER, EVSE, batteries, prosumers, archetypes, synthetic asset and load-profile generation. | Power-flow execution, dashboard publication, settlement. |
| `gridalyn.simulation` | Solver adapters, power-flow execution, Monte Carlo orchestration, physical validation. | Domain meaning of assets, dashboard publication, study-specific scenario policy. |
| `gridalyn.operations` | Providers, constraints, clearing, dispatch, settlement, operational KPIs. | Building canonical network models or generating base asset tables. |
| `gridalyn.projects` | The StudyProject and Workflow contracts, the runner, regression and sense checks. | Reusable domain logic. |
| `gridalyn.interfaces` | CLI entry points, report and dashboard surfaces, visualization adapters. | Core modeling or simulation assumptions. |

Common cases:

| Need | Put it in |
| --- | --- |
| GeoJSON footprint parsing | `gridalyn.twin.adapters` or `gridalyn.twin.geoprocess` |
| Building, device or DER entities | `gridalyn.assets.modeling` |
| Transformer thermal model primitives | `gridalyn.assets.modeling` |
| Synthetic heating and background load profiles | `gridalyn.assets.datagen` |
| Synthetic weather-to-thermal-limit generation | `gridalyn.assets.datagen` |
| GeoJSON-to-pandapower network construction | `gridalyn.twin.adapters.pandapower_builder` (the builder); `gridalyn.simulation.simulators.powerflow` orchestrates and solves it |
| Pandapower or LightSim2Grid execution | `gridalyn.simulation` |
| Dashboard catalogs and visualization surfaces | `gridalyn.interfaces` |
| Flexibility provider selection | `gridalyn.operations` |
| A workflow stage that pins paths and parameters | `projects/<name>/scripts/` |

Where generated files go is covered in
[Development Workflow](developer-workflow.md#where-files-belong).

## Decisions already made

- Transformer thermal behaviour is native to `gridalyn.assets.modeling`;
  datagen may use it to build synthetic stress-test assumptions, but modeling
  never imports datagen.
- Simulation produces solver results. The study workflow or the twin instance
  decides where they are written and how the dashboard consumes them;
  dashboard publication belongs to catalog and report contracts, not to
  simulation exporters.
- `gridalyn.assets.datagen.MVNetwork` is an aggregate synthetic stress-test
  model with explicit configuration, not an import-time binding to one study's
  config file.
- Operations consumes network constraints through the `NetworkConstraintModel`
  protocol (`gridalyn/operations/constraints.py`). A study may pass an
  `MVNetwork`; operations modules do not import datagen.
- Settlement is baseline-free: `calculate_period_settlement`
  (`gridalyn/operations/settlement.py`) takes the absolute contractual cap
  `p_cap_limit_kw` recorded at clearing, and raises when a positive cleared
  volume arrives without one.
- Workspace-level validation may inspect study contracts through a late-bound
  project API, but `foundation` never becomes a facade for the layers above it.
- When a path, format or alias is retired, its callers move to the owning
  module; parallel implementations are not kept.

## Before adding or moving a module

- Is this an entity or model definition, or a solver execution?
- Does it create canonical twin state, or consume it?
- Does it encode an assumption that belongs to one study in `projects/<name>/`?
- Can another study reuse it without importing a sibling study's scripts?
- Can its generated output be reproduced through a declared workflow?
