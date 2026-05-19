# SDK Public Contract

The canonical Python package namespace is `gridalyn`. New applications and
project scripts should use `gridalyn` imports directly.

## Stable Facade

Prefer importing platform-level helpers from `gridalyn.foundation`,
`gridalyn.projects`, and the other seven platform modules:

```python
from gridalyn import foundation, projects, twin

project = projects.load_project("projects/flexibility_cls")
workspace = foundation.validate_workspace(".")
repository = twin.NetworkModelRepository("instances/default/digital_twin/base")
```

These imports are intended for project scripts, tests, applications, and
automation. Historical imports such as `gridalyn.platform` and
`gridalyn.network` remain available for compatibility.

## Domain Modules

Use domain modules when you are building reusable platform capabilities:

| Module | Use it for |
| --- | --- |
| `gridalyn.twin` | Durable network topology, adapters, semantic graph, and repository access. |
| `gridalyn.assets` | Synthetic network, building, EVSE, DER, thermal, and load model generation. |
| `gridalyn.simulation` | Power-flow engines, network impact, validation, and surrogate-ready features. |
| `gridalyn.operations` | Flexibility providers, clearing, dispatch, settlement, and KPIs. |
| `gridalyn.foundation` | Validation, manifests, artifact policy, report metadata, and governance. |
| `gridalyn.interfaces` | CLI, dashboard/report/catalog helpers, graph-facing adapters, and visualization. |

## Seven-Module Direction

The public contract includes seven larger capability areas:

```text
foundation -> twin -> assets -> simulation -> operations -> projects -> interfaces
```

Compatibility imports remain part of the contract for this release so existing
projects keep running. New code should choose the seven-module surface unless it
is deliberately maintaining an older workflow:

| Target area | Historical aliases kept for compatibility |
| --- | --- |
| Foundation | `gridalyn.platform`, `gridalyn.reporting` |
| Twin | `gridalyn.network`, `gridalyn.adapters`, `gridalyn.io`, `gridalyn.semantic` |
| Assets | `gridalyn.modeling`, `gridalyn.datagen` |
| Simulation | `gridalyn.simulators`, `gridalyn.analytics` |
| Operations | `gridalyn.operations`, `gridalyn.market` |
| Projects | `gridalyn.projects`, `gridalyn.workflows` |
| Interfaces | `gridalyn.interfaces.cli` and dashboard/report/catalog helpers |

The seven modules provide the product vocabulary:

```python
from gridalyn import foundation, twin, assets, simulation, operations, projects, interfaces
```

Future deeper moves should keep the old documented import as a compatibility
path until projects and tutorials have migrated.

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
| `outputs/json/` | Legacy or compatibility JSON outputs when needed. |
| `outputs/reports/` | Stable JSON reports with the platform report contract. |
| `outputs/operations/` | Dispatch instructions, operation runs, settlement-ready tables, and operational catalogs. |
| `outputs/manifests/` | Run manifests and artifact inventories. |

## Compatibility Rule

Do not depend on private helper modules from another project workspace. A study
can depend on `gridalyn`, declared inputs, and generated artifacts, but not on
hidden scripts inside a different study.

## Synthetic Network API

The assets module exposes the GeoJSON-to-network builder:

```python
from gridalyn.assets import build_synthetic_network_from_geojson

result = build_synthetic_network_from_geojson(
    footprints_path="projects/my_project/inputs/buildings.geojson",
    config_path="configs/grid/config.json",
    out_dir="projects/my_project/outputs/cache",
    clustering_crs="auto",
    write_cache=True,
)
```

This is the preferred path for project workflows that need synthetic networks.
Lower-level `PowerGridGraph` methods remain available for library development
and experiments, but project stages should prefer the builder because it emits
a consistent validation report and cache contract.
