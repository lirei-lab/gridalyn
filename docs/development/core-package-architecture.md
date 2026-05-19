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
| `gridalyn.assets` | Building, load, EV/EVSE, DER, forecast, thermal, and synthetic asset generation. |
| `gridalyn.simulation` | Simulation engines, pandapower integration, network impact, and validation analytics. |
| `gridalyn.operations` | Providers, aggregators, offers, clearing, dispatch, settlement, constraints, and KPIs. |
| `gridalyn.projects` | Project/workflow manifests, workflow stages, regression checks, and reproducible study orchestration. |
| `gridalyn.interfaces` | CLI modules, dashboard/report contracts, visualization, and user/system entrypoints. |

Anything tied to a particular public study belongs under `projects/`.
Tutorial datasets belong under `examples/tutorials/data`.
Generated artifacts belong under declared output folders such as
`projects/*/outputs`, `instances/default/digital_twin/*`, or `examples/generated`.

## Compatibility Imports

The old domain imports remain available through compatibility aliases so
existing project scripts and tutorials continue to run:

```text
gridalyn.network      -> gridalyn.twin.network
gridalyn.adapters     -> gridalyn.twin.adapters
gridalyn.modeling     -> gridalyn.assets.modeling
gridalyn.simulators   -> gridalyn.simulation.simulators
gridalyn.analytics    -> gridalyn.simulation.analytics
gridalyn.market       -> gridalyn.operations.market
gridalyn.platform     -> gridalyn.foundation.platform
gridalyn.interfaces.cli          -> gridalyn.interfaces.cli
```

New code should prefer the seven-module vocabulary when it is clearer.
Compatibility imports are for continuity, not for adding new architectural
surface.

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
multiple applications a cleaner API. Each move needs compatibility imports,
hygiene tests, documentation, and a project regression run.

## Data and Artifact Rules

- `gridalyn/foundation/data` contains only lightweight dataset discovery code. It must not
  contain real GeoJSON, Parquet, HDF5, or case-study files.
- Runtime caches must not be tracked inside SDK packages. The datagen weather
  cache defaults to `examples/generated/cache` and can be redirected with
  `GRIDALYN_DATAGEN_CACHE_DIR` or the legacy `GEOPOWER_DATAGEN_CACHE_DIR`.
- `__pycache__`, generated outputs, and cache folders are never source files.
- Model weights are currently retained under `gridalyn/assets/datagen/models/weights`
  because `ParametricArxGenerator` loads them at runtime. Moving them should be
  done through a model registry change, not by silently deleting them.

## Public API Direction

The intended public surface is:

```text
gridalyn.foundation     governance, validation, manifests, reports metadata
gridalyn.twin           network model, topology, adapters, semantic graph
gridalyn.assets         building, EV, DER, load, forecast, synthetic models
gridalyn.simulation     powerflow, thermal, surrogate, validation analytics
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

project = projects.load_project("projects/flexibility_cls")
report = foundation.check_artifact_policy(".")
repository = twin.NetworkModelRepository("instances/default/digital_twin/base")
```

Synthetic grid generation from building footprints should use the GeoJSON
adapter namespace:

```python
from gridalyn.twin.adapters.geojson import FakeGeoJSONGenerator, GridProcessor
from gridalyn.twin.core.graph import PowerGridGraph

generator = FakeGeoJSONGenerator(grid_size=8, rectangular=True)
payload = generator.generate_geojson()
```

Source-specific acquisition belongs in examples or project inputs, not in the
core package. OSMnx downloads and Microsoft Global ML Building Footprints
conversion are documented in
[Synthetic Networks From GeoJSON](../tutorials/synthetic-network-from-geojson.md).
The package boundary stays stable: `gridalyn.twin.adapters.geojson` validates
and prepares footprints, while projects decide which source data they trust and
how they record lineage. The older `gridalyn.adapters.geojson` import remains
available for compatibility.

Market and flexibility studies should import reusable selection logic directly
from `gridalyn.operations`:

```python
from gridalyn.operations import (
    apply_spatial_cls,
    build_locational_clearing,
    build_provider_registry,
)
```

Historical study scripts have been absorbed into governed project workspaces.
New code should use the platform package or project-local scripts, and no SDK
module should import project runtime logic.

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
- tracked `gridalyn` and `gridalyn` files do not include generated cache/output directories;
- CLI modules dispatch to package modules and workflow entrypoints;
- the datagen weather cache defaults outside the package tree;
- Monte Carlo exports do not default to publication or paper data paths.

These tests are intentionally conservative. If a new package-level artifact is
needed, add a clear architectural reason first, then update the guardrail with
an explicit exception.
