# Project Hygiene

The canonical runtime state for the default digital twin instance lives under
`instances/default/digital_twin/`. Generated
local experiments, one-off debug scripts, and embedded database files should
not be committed as project source.

## Removed Legacy Artifacts

The following paths were removed from version control:

- `scratch/`: ad hoc debug and patch scripts for old DSO experiments.
- `data/twins/`: local FalkorDB database files created by the legacy
  `DigitalTwinManager`.

Both paths are now ignored by `.gitignore`.

## Current Source Of Truth

Use these logical folders for active workflows. They live inside the default
runtime instance at `instances/default/digital_twin/`:

- `instances/default/digital_twin/base`: static grid and building assets.
- `instances/default/digital_twin/scenarios`: scenario and asset registry metadata.
- `instances/default/digital_twin/timeseries`: scenario power-flow and load traces.
- `instances/default/digital_twin/dashboard/catalog.json`: dashboard scenario catalog.
- `instances/default/digital_twin/semantic`: semantic graph artifacts.
- `instances/default/digital_twin/reports`: canonical grid reports.
- `instances/default/digital_twin/flexibility`: provider registry, network sensitivity, and
  network-impact surrogate artifacts.

## Legacy Export Boundary

`gridalyn.db.DigitalTwinManager` and `DashboardExporter` are retained for
archived Falkor/DuckDB experiments, but they are not the current dashboard or
digital-twin publication path.

`gridalyn.db.__all__` now exposes only `FederatedGraphAdapter`. The old
`DigitalTwinManager`, `FalkorAdapter`, `DuckAdapter`, and `DashboardExporter`
remain importable through lazy deprecation shims so archived tutorials can still
run while new application code follows the federated semantic graph contract.

By default, `DigitalTwinManager.export_web_snapshot()` now refuses to write into
`dashboard/public/data`. Archived demos must opt in explicitly with:

```python
DigitalTwinManager(
    twin_id="legacy_demo",
    allow_legacy_dashboard_public_export=True,
)
```

New work should publish dashboard state through
`instances/default/digital_twin/dashboard/catalog.json` and the scenario Parquet files under
`instances/default/digital_twin/timeseries`.

Kepler/dashboard-public exporters in `gridalyn.io.geo` are also legacy
publication helpers. They emit a deprecation warning and should only be used for
archived demos that still consume `dashboard/public`.

The old monolithic `gridalyn/datagen/run_simulation.py` CLS script was removed.
It duplicated project workflow behavior and referenced obsolete subpackages;
the maintained path is project workspaces plus the stable `gridalyn.platform`,
`gridalyn.workflows`, and `gridalyn.interfaces.cli` entry points.

GeoJSON preprocessing for synthetic network generation now has a canonical API:
`gridalyn.adapters.geojson`. The historical `gridalyn.geoprocess` package is
kept as a compatibility namespace, but active tests, tutorials, and
data-acquisition examples should reference the adapter path.

`gridalyn.viz` is intentionally narrow. It exposes Folium inspection maps via
`GridPlotter` for synthetic-grid development and tutorials. Offline MP4/GIF
animation code that targeted legacy Kepler Parquet snapshots was removed from
the package because the dashboard and project reports now consume canonical
digital-twin artifacts directly.

The legacy tutorial `examples/tutorials/create_grid_with_datagen_parallel.py`
now requires:

```bash
--allow-legacy-dashboard-public
```

## Current Build Entry Point

Use the digital-twin build orchestrator for active regeneration work:

```bash
uv run gridalyn twin build --dry-run --skip-heavy
uv run gridalyn twin build --include-network-impact
```

The orchestrator writes `instances/default/digital_twin/reports/digital_twin_build_manifest.json`
and keeps generated artifacts inside the canonical `instances/default/digital_twin/` contract.

## Removed Paper Snapshot

`paper/data` was removed from the active tree. It contained two small Monte
Carlo snapshots:

- `substation_baseline_mc.parquet`;
- `substation_powerflow_mc.parquet`.

Those files duplicated data that now belongs under
`projects/flexibility_cls/outputs/data` or `instances/default/digital_twin/timeseries`.
`MonteCarloSimulationManager.export_to_parquet()` no longer defaults to
`paper/data`; callers must pass an explicit output directory only for legacy
reproducibility snapshots.

## Similar Cleanup Candidates

The following tracked paths have the same smell as `paper/data`: they are
generated snapshots, build outputs, caches, or archived copies outside the
current digital-twin contract.

- `_build/`: tracked Sphinx/MkDocs HTML build output. Regenerate locally instead
  of versioning it.
- `dashboard/public/`: removed from the active tree. It was a legacy
  Kepler/static dashboard bundle; the current dashboard reads mounted
  `instances/default/digital_twin/` and `projects/*/outputs/` artifacts.
- `examples/generated/outputs/`: tutorial-only generated maps or caches from
  examples. Project runtime caches belong under `projects/*/outputs/cache`.
- `examples/generated/cache/` and root `cache/`: request/download cache JSON files.
- old paper and figure backup copies: preserve in git history or an external
  archive, not as active source.

Do not remove the default twin instance wholesale because it is the canonical
platform artifact layer. Its physical home is
`instances/default/digital_twin/`. Project-generated data
belongs under `projects/*/outputs`; it is not the active dashboard or package
source path.

## Examples Cleanup Policy

`examples/` is now organized around public tutorials and data-acquisition
demos. Production workflows should use
`gridalyn.interfaces.cli` commands such as:

```bash
uv run gridalyn twin build --dry-run
uv run gridalyn market verify-clearing --scenario-id S4
uv run gridalyn semantic validate
uv run gridalyn dashboard catalog
```

Compatibility scripts no longer live under `examples/`. The first extracted workflows are
`gridalyn.workflows.digital_twin.ev_scenarios`,
`gridalyn.workflows.digital_twin.ev_timeseries`, and
`gridalyn.workflows.flexibility.locational_verification`. Generated Python caches can
be deleted at any time. Data caches under `examples/generated/cache`,
`examples/generated/outputs`, or root `cache` are tutorial or local caches and
must not be project runtime dependencies.

Shared grid and geography configurations live under `configs/`, not
`examples/`. Project manifests, workflows, and reusable package defaults should
reference `configs/grid/*.json` and `configs/geography/*.json` so examples stay
tutorial-only.

For the active cleanup queue, see [Cleanup Inventory](cleanup-inventory.md).
