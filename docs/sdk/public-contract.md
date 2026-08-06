# SDK Public Contract

The canonical Python package namespace is `gridalyn`. New applications and
project scripts should use `gridalyn` imports directly.

## Stable Facade

Prefer importing platform-level helpers from `gridalyn.foundation`,
`gridalyn.projects`, and the other seven platform modules:

```python
from gridalyn import foundation, projects, twin

project = projects.load_project("projects/ev_hosting_flex")
workspace = foundation.validate_workspace(".")
repository = twin.NetworkModelRepository("instances/default/digital_twin/base")
```

These imports are intended for project scripts, tests, applications, and
automation.

Note that `foundation.validate_workspace` is a socket filled in by the projects
layer: reached through `gridalyn.foundation` alone it raises a located
`RuntimeError` naming the remedy until `gridalyn.projects` (or any module that
imports it, such as the CLI) has been imported.

## Domain Modules

Use domain modules when you are building reusable platform capabilities:

| Module | Use it for |
| --- | --- |
| `gridalyn.twin` | Durable network topology, adapters, semantic graph, and repository access. |
| `gridalyn.assets` | Building, EVSE, DER, thermal, load, forecast, and asset-table generation. |
| `gridalyn.simulation` | Synthetic-network building, power-flow engines, network impact, validation, and surrogate-ready features. |
| `gridalyn.operations` | Flexibility providers, clearing, dispatch, settlement, and KPIs. |
| `gridalyn.foundation` | Validation, manifests, artifact policy, report metadata, and governance. |
| `gridalyn.projects` | Project manifests, workflow execution, project status, regression, and sense checks. |
| `gridalyn.interfaces` | CLI, dashboard/report/catalog helpers, graph-facing adapters, and visualization. |

## Seven-Module Direction

The public contract includes seven larger capability areas:

They are a vocabulary, not a single linear import chain. Lower layers own
durable contracts; upper layers orchestrate or expose them.

The seven modules are the product vocabulary:

```python
from gridalyn import foundation, twin, assets, simulation, operations, projects, interfaces
```

Public applications should treat these seven modules as the stable import
surface.

## Project Scripts

Project scripts should be thin orchestration layers:

```text
load inputs -> call Gridalyn library function -> write declared artifact
```

If a function would be useful in a second project, place it in the Gridalyn SDK.
If it only binds a specific workflow stage to paths and parameters, keep it in
the project workspace.

## Output Contract

Use these output folders consistently:

| Folder | Purpose |
| --- | --- |
| `outputs/data/` | Derived analytical tables. |
| `outputs/figures/` | Figures generated from project data. |
| `outputs/json/` | Auxiliary JSON outputs for project-local stage data. |
| `outputs/reports/` | Stable JSON reports with the platform report contract. |
| `outputs/operations/` | Dispatch instructions, operation runs, settlement-ready tables, and operational catalogs. |
| `outputs/manifests/` | Run manifests and artifact inventories. |

## Project Boundary Rule

Do not depend on helper modules from another project workspace. A study can
depend on `gridalyn`, declared inputs, and generated artifacts, but not on
hidden scripts inside a different study.

## Synthetic Network API

The GeoJSON-to-pandapower builder lives in `gridalyn.simulation`, because it
creates solver-ready network objects and optional validation reports:

```python
from gridalyn.simulation import build_synthetic_network_from_geojson

result = build_synthetic_network_from_geojson(
    footprints_path="projects/my_project/inputs/buildings.geojson",
    config_path="configs/grid/config.json",
    out_dir="projects/my_project/outputs/cache",
    clustering_crs="auto",
    write_cache=True,
)
```

This is the preferred path for project workflows that need synthetic networks.
Lower-level topology builders remain internal library development tools. Public
project stages should prefer the builder because it emits a consistent
validation report and cache contract.
