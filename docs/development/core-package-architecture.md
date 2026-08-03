# Gridalyn SDK Architecture

`gridalyn` is the reusable library layer of the platform. Project workspaces,
dashboards, and examples may call it, but the SDK should not depend on a single
case study or keep generated study outputs inside its source tree.

The implementation lives under `gridalyn/`, which is the canonical and only SDK
namespace for new applications and project scripts.

## Package Boundary

The physical SDK tree is organized around seven platform modules:

| Module | Responsibility |
| --- | --- |
| `gridalyn.foundation` | IDs, units, lineage, validation, manifests, model versions, artifact policy, and lightweight dataset discovery. |
| `gridalyn.twin` | Network topology, adapters, import/export helpers, semantic graph, and graph/database adapters. |
| `gridalyn.assets` | Building, load, EV/EVSE, DER, forecast, thermal, and asset-table generation. |
| `gridalyn.simulation` | Synthetic-network builders, simulation engines, pandapower integration, network impact, and validation analytics. |
| `gridalyn.operations` | Providers, aggregators, offers, clearing, dispatch, settlement, constraints, and KPIs. |
| `gridalyn.projects` | Project/workflow manifests, workflow stages, regression checks, and reproducible study orchestration. |
| `gridalyn.interfaces` | CLI modules, dashboard/report contracts, visualization, and user/system entrypoints. |

Anything tied to a particular public study belongs under `projects/`.
Tutorial datasets belong under `examples/tutorials/data`.
Generated artifacts belong under declared output folders such as
`projects/*/outputs`, `instances/default/digital_twin/*`, or `examples/generated`.

## Public Module Vocabulary

The seven modules above are the public vocabulary for new applications,
projects, examples, and documentation. Put reusable behavior in the owning
native module and keep project scripts as thin orchestration wrappers.

See [Module Boundaries](module-boundaries.md) for the ownership and dependency
rules.

| Platform module | Internal subpackages |
| --- | --- |
| `foundation` | `platform`, `data` |
| `twin` | `network`, `adapters`, `core`, `io`, `semantic`, `db`, `geoprocess` |
| `assets` | `modeling`, `datagen` |
| `simulation` | `simulators`, `analytics` |
| `operations` | `flexibility`, `market`, operation-run contracts |
| `projects` | project manifest loader/runner, `workflows` |
| `interfaces` | `cli`, `reporting`, `viz` |

Further moves should happen only when they reduce ambiguity for users or give
multiple applications a cleaner API. Each move needs native imports, hygiene
tests, documentation, and a project regression run.

## Data and Artifact Rules

- `gridalyn/foundation/data` contains only lightweight dataset discovery code. It must not
  contain real GeoJSON, Parquet, HDF5, or case-study files.
- Runtime caches must not be tracked inside SDK packages. The datagen weather
  cache defaults to `examples/generated/cache` and can be redirected with
  `GRIDALYN_DATAGEN_CACHE_DIR`.
- `__pycache__`, generated outputs, and cache folders are never source files.
- Optional model weights may live under `gridalyn/assets/datagen/models/weights`
  and are declared as package data when present.
  `gridalyn.assets.datagen.load_profiles.ParametricArxGenerator` also has an
  analytical fallback so public clones and lightweight installs do not depend on
  local training data or binary artifacts. Moving the weights should be
  done through a model registry change, not by silently changing the generator
  contract.

## Public API Direction

The intended public surface is:

```text
gridalyn.foundation     governance, validation, manifests, reports metadata
gridalyn.twin           network model, topology, adapters, semantic graph
gridalyn.assets         building, EV, DER, load, forecast, asset models
gridalyn.simulation     synthetic-network building, powerflow, thermal, surrogate, validation analytics
gridalyn.operations     providers, aggregators, clearing, dispatch, settlement
gridalyn.projects       project.yaml/workflow.yaml, workflows, regressions
gridalyn.interfaces     CLI, report/dashboard contracts, graph/UI interfaces
```

Script entrypoints should call these modules instead of reimplementing workflow
logic. New case studies should start in `projects/`, not in `examples/`.

Reusable path handling belongs in `gridalyn.foundation`:

```python
from gridalyn.foundation import workspace_from_path

workspace = workspace_from_path(".")
cache_dir = workspace.layout.cache
base_dir = workspace.layout.base
```

Reusable building-footprint preprocessing belongs in
`gridalyn.twin.geoprocess`. The `examples/data_acquisition` scripts are
tutorial wrappers over that SDK surface.

The recommended user-facing command is `gridalyn`, for example
`gridalyn project run ...` or `gridalyn twin build ...`. The recommended
developer-facing API can use either the seven-module surface or the specific
subpackage:

```python
from gridalyn import foundation, projects, twin

project = projects.load_project("projects/ev_hosting_flex")
report = foundation.check_artifact_policy(".")
repository = twin.NetworkModelRepository("instances/default/digital_twin/base")
```

Synthetic grid generation from building footprints should use the GeoJSON
adapter namespace for footprint creation and validation:

```python
from gridalyn import simulation
from gridalyn.twin.adapters.geojson import FakeGeoJSONGenerator

generator = FakeGeoJSONGenerator(grid_size=8, rectangular=True)
payload = generator.generate_geojson()

result = simulation.build_synthetic_network_from_geojson(
    footprints_path="projects/my_project/inputs/buildings.geojson",
    config_path="configs/grid/config.json",
    out_dir="projects/my_project/outputs/cache",
)
```

Source-specific acquisition belongs in examples or project inputs, not in the
core package. OSMnx downloads and Microsoft Global ML Building Footprints
conversion are documented in
[Synthetic Networks From GeoJSON](../tutorials/synthetic-network-from-geojson.md).
The package boundary stays stable: `gridalyn.twin.adapters.geojson` validates
and prepares footprints, while projects decide which source data they trust and
how they record lineage.

When footprints need to become a solver-ready electrical network, use the
simulation-owned builder:

```python
from gridalyn.simulation import build_synthetic_network_from_geojson

result = build_synthetic_network_from_geojson(
    footprints_path="projects/my_project/inputs/buildings.geojson",
    config_path="configs/grid/config.json",
)
```

Synthetic load, weather, thermal forecast generation, and aggregate MV-network
stress-test assumptions live under `gridalyn.assets.datagen`. That package is a
documented experimental surface: examples and advanced workflows may import it
directly, while stable asset entities and pure physical model contracts should
continue to be exposed through `gridalyn.assets.modeling` and the
`gridalyn.assets` facade.

Market and flexibility studies should import reusable selection logic directly
from `gridalyn.operations`:

```python
from gridalyn.operations import (
    apply_spatial_cls,
    build_locational_clearing,
    build_provider_registry,
)
```

Study scripts belong in governed project workspaces. New code should use the
platform package or project-local scripts, and no SDK module should import
project runtime logic.

`gridalyn.projects.workflows.scripts` contains script entrypoints, not domain
logic. Stable commands in `gridalyn.interfaces.cli` should dispatch to SDK
functions or thin workflow modules, and reusable behavior should continue
moving toward `gridalyn.twin`, `gridalyn.operations`, `gridalyn.simulation`, or
`gridalyn.assets`. This keeps the dependency direction correct: examples and
projects may depend on `gridalyn`, but the SDK must not depend on them.

## Hygiene Guardrails

The repository includes hygiene tests that enforce the current boundary:

```bash
uv run --with pytest python -m pytest tests/test_project_hygiene.py -q
```

Those tests check that:

- `gridalyn/foundation/data` only tracks discovery code;
- tracked package and project files do not include generated cache/output directories;
- CLI modules dispatch to package modules and workflow entrypoints;
- the datagen weather cache defaults outside the package tree;
- Monte Carlo exports do not default to publication or draft artifact paths.

These tests are intentionally conservative. If a new package-level artifact is
needed, add a clear architectural reason first, then update the guardrail with
an explicit exception.
