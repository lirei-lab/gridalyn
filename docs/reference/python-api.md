# Python API Reference

This page is for developers who build workflows, reports, dashboards, adapters
or automation on top of Gridalyn without depending on study-specific scripts.
It says which module to import for what, which import paths are supported, and
shows a few verified calls; the rest of the page is rendered by `mkdocstrings`
from the source docstrings, so it cannot disagree with the code.

## Which facade for what

Each layer of the [stack](../components/overview.md) has one facade module, and
that is the import path to use. The component page explains the concepts; this
page lists the names.

| Import | For | Concepts |
| --- | --- | --- |
| `gridalyn.foundation` | Workspaces and artifact paths, the report contract and its uncertainty estimates, manifests, artifact policy, governance records. | [Foundation](../components/foundation.md) |
| `gridalyn.twin` | The canonical network model and its identity, the repository that loads and validates it, source adapters, observed state (simulated and measured), the semantic graph. | [Twin](../components/twin.md) |
| `gridalyn.assets` | Building, EV, DER and thermal asset models, and synthetic load and scenario generation. | [Assets](../components/assets.md) |
| `gridalyn.simulation` | Feeder and synthetic-network builders, power flow and its backends, surrogates, channel models, network-impact analytics. | [Simulation](../components/simulation.md) |
| `gridalyn.operations` | Providers, locational clearing, dispatch, settlement, KPIs, operation-run records, agent interaction. | [Operations](../components/operations.md) |
| `gridalyn.projects` | The `StudyProject` and `Workflow` contract, the runner, typed input loaders, sense checks, regression. | [Projects](../components/projects.md) |
| `gridalyn.interfaces` | CLI entry points, reporting catalogs, plotting helpers. | [Interfaces](../components/interfaces.md) |

The top-level `gridalyn` module re-exports a curated subset of those facades,
so a script can write `from gridalyn import build_ieee33_benchmark_feeder`
without knowing which layer owns it. Each of its names is documented once,
under its owning facade.

## What is supported

- **The layer facades above**, and every name in their `__all__`.
- **These sub-packages**, whose names are only partly re-exported by a facade:
  `gridalyn.twin.network`, `gridalyn.twin.observation`,
  `gridalyn.simulation.backends`, `gridalyn.simulation.surrogates`,
  `gridalyn.simulation.policies`, `gridalyn.simulation.channels`,
  and `gridalyn.operations.interaction`. Each is rendered under
  [Stable sub-packages](#stable-sub-packages) below.
- **Nothing else.** Any other module path — for example
  `gridalyn.simulation.simulators.powerflow.synthetic_network` rather than
  `gridalyn.simulation` — is an implementation detail and may move between
  releases.

Project scripts may orchestrate a study, but they should not become hidden
platform APIs: when a second workflow needs the same behaviour, move it into
`gridalyn` and keep the script a thin wrapper.

## Examples

Every block below was run as shown from the root of a repository checkout.
Blocks that read the twin instance need it built first
([Build A Twin](../guides/build-a-twin.md)). Writing a governed report is
covered in [Write Governed Reports And Figures](../guides/reports-and-figures.md).

### Projects

```python
from gridalyn import projects

created = projects.init_project("projects/my_case", name="my_case")
project = projects.load_project(created.root)
stages = projects.plan_project(project)
status = projects.project_status(project.root, check_artifacts=True)
print([stage.id for stage in stages], status["valid"])
```
```text
['prepare_inputs', 'validate_outputs'] True
```

`project_verify`, `project_verify_all`, `project_sense_check` and
`project_regression` are the Python side of the check ladder described in
[Testing And Validation](../contributing/testing-and-validation.md).
`project_regression` returns `valid: False`, naming the missing file, when the
project has no `baselines/results_baseline.json`.

### The network model

`NetworkModelRepository.from_parquet` takes the instance's base-artifact
directory. Ask the workspace layout for it rather than writing the path, so the
call also type-checks:

```python
from gridalyn import foundation, twin

layout = foundation.workspace_from_path(".").layout
repo = twin.NetworkModelRepository.from_parquet(layout.base)
model = repo.load_model()
downstream = repo.get_downstream("transformer:25")
equipment = repo.get_connected_equipment("bus:17")
integrity = repo.validate_integrity()
print(model.operational_state, integrity.valid)
```
```text
base True
```

What `load_model()` resolves (identity, provenance policy, operational state)
and what `validate_integrity()` checks are described in
[Twin](../components/twin.md#the-contract).

### Source adapters

```python
from gridalyn import twin

registry = twin.default_network_adapter_registry()
for descriptor in registry.list_descriptors():
    print(descriptor.adapter_id, descriptor.source_format, descriptor.geographic_crs)
```
```text
cim_parquet cim-parquet None
pandapower_topology pandapower-net None
synthetic_pandapower pandapower-cache EPSG:4326
```

An adapter satisfies the `NetworkSourceAdapter` protocol, and its `export()`
returns a `NetworkExportResult` whose required `identity` is the
`ModelIdentity` read back from the manifest the export just wrote. The shipped
adapters obtain it with `exported_model_identity(out_dir)`, exported by
`gridalyn.twin`, so producer and consumer are proven to agree
rather than assumed to. [Twin](../components/twin.md) describes each adapter.

### Semantic graph queries

`SemanticGraphRepository` answers generic graph questions; the flexibility
questions are free functions of the capability that adds them. With a graph
built by `gridalyn semantic build`
([Semantic Graph](semantic-graph.md#build-and-validate)):

```python
from gridalyn import twin
from gridalyn.twin.semantic.capabilities.flexibility import (
    query_providers_for_constraint,
    query_trace_building_to_constraint,
)

graph = twin.SemanticGraphRepository.from_parquet(
    "instances/default/digital_twin/semantic"
)
providers = query_providers_for_constraint(graph, "transformer:64", scenario_id="S4")
trace = query_trace_building_to_constraint(graph, "building:1131", scenario_id="S4")
print(len(providers), "providers in the transformer:64 zone")
print(trace["bus_ids"], trace["constraint_ids"])
```
```text
16 providers in the transformer:64 zone
('bus:1131',) ('transformer:64',)
```

### Synthetic load profiles

```python
from gridalyn import assets

profiles = assets.generate_residential_load_profiles(
    20, day="cold", resolution_minutes=15, seed=42, weather="synthetic"
)
print(profiles.shape, list(profiles.columns[:3]))
```
```text
  Coldest day: 2023-12-18  (daily mean -18.3 °C)
(96, 20) ['unit_000', 'unit_001', 'unit_002']
```

`weather="synthetic"` keeps the result byte-stable across machines. The
default, `"auto"`, fetches a PVGIS typical meteorological year over the
network. Record the generator, seed and weather window in the study's report.

### Power flow

```python
from gridalyn import simulation

registry = simulation.default_powerflow_backend_registry()
print([descriptor.backend_id for descriptor in registry.list_descriptors()])

net = simulation.build_ieee33_benchmark_feeder()
simulation.solve_power_flow(net, backend_id="pandapower_native")
print(f"min bus voltage: {net.res_bus.vm_pu.min():.4f} pu")
```
```text
['lightsim2grid', 'pandapower_native']
min bus voltage: 0.9131 pu
```

`lightsim2grid` is listed whether or not it is installed; resolving it on an
install without the `sim` extra raises `MissingCapabilityError`.

## How this page is rendered

Most facade names are declared in a `_LAZY_EXPORTS` map and resolved on first
access through a module-level `__getattr__`, so `import gridalyn` stays cheap
and never imports a truly optional dependency (`lightsim2grid`, `cvxpy`,
`osmnx`) until something needs it; see
[Conventions](../contributing/conventions.md#lazy-exports). A few names that
pull in no optional dependency are imported eagerly instead.

A lazy name does not exist in the module namespace until it is touched, so
static analysis finds no members. The `mkdocstrings` handler is therefore
configured with `force_inspection: true`: it imports each module and reads its
members, which resolves every `_LAZY_EXPORTS` entry. Each facade also defines
`__dir__`, so `dir()` and `inspect.getmembers` report the same names this page
does.

A name is shown only when the object it resolves to carries a docstring. An
undocumented name is still importable and supported; it appears here once it
is described at its definition.

## Layer facades

::: gridalyn
    options:
      members: false
      heading_level: 3

::: gridalyn.foundation
    options:
      heading_level: 3

::: gridalyn.twin
    options:
      heading_level: 3

::: gridalyn.assets
    options:
      heading_level: 3

::: gridalyn.simulation
    options:
      heading_level: 3

::: gridalyn.operations
    options:
      heading_level: 3

::: gridalyn.projects
    options:
      heading_level: 3

::: gridalyn.interfaces
    options:
      heading_level: 3

## Stable sub-packages

::: gridalyn.twin.network
    options:
      heading_level: 3

::: gridalyn.twin.observation
    options:
      heading_level: 3

::: gridalyn.simulation.backends
    options:
      heading_level: 3

::: gridalyn.simulation.surrogates
    options:
      heading_level: 3

::: gridalyn.simulation.policies
    options:
      heading_level: 3

::: gridalyn.simulation.channels
    options:
      heading_level: 3

::: gridalyn.operations.interaction
    options:
      heading_level: 3

## Not covered here

- **Private submodules.** Anything not named in a facade's or a stable
  sub-package's `__all__` carries no stability promise.
- **Command-line usage.** See the [CLI Reference](cli.md).
- **YAML contracts.** See the [Project And Workflow YAML](workflow-yaml.md)
  reference and the [Report And Run-Manifest Schema](report-schema.md).
