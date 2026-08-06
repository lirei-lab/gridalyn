# Digital Twin

The digital twin is the stable asset and scenario layer used by project
workflows, the dashboard, and semantic graph tooling. It is not a database
service; it is a materialized workspace of Parquet and JSON artifacts that can
later be loaded into DuckDB, FalkorDB, or another operational backend.

The default runtime instance lives at:

```text
instances/default/digital_twin/
```

This is the only default digital-twin path. Commands, tests, documentation, and
dashboard mounts should resolve through `ArtifactLayout` or explicit
`instances/<name>/digital_twin/` paths, not through a repository-root alias.

## Directory Contract

```text
instances/default/digital_twin/
  base/
    buildings.parquet
    building_grid_connectivity.parquet
    grid_buses.parquet
    grid_lines.parquet
    grid_transformers.parquet
    metadata.json
  models/
    building_models.parquet
    thermal_zones.parquet
    device_registry.parquet
    end_use_loads.parquet
    building_model_manifest.json
    scenarios/
      S*_device_registry.parquet
      scenario_summary.parquet
      scenario_model_manifest.json
  dashboard/
    catalog.json
  scenarios/
    S0.json ... S4.json
    ev_assignments.parquet
    asset_registry.parquet
    asset_registry_summary.json
    index.json
  timeseries/
    S*_ev_load.parquet
    S*_powerflow_*.parquet
    ev_load_summary.json
    powerflow_smoke_summary.json
  flexibility/
    provider_registry.parquet
    network_sensitivity.parquet
    provider_registry_summary.json
    network_graph_nodes.parquet
    network_graph_edges.parquet
    network_node_features.parquet
    network_edge_features.parquet
    network_impact_training.parquet
    network_impact_predictions.parquet
    network_impact_surrogate_report.json
    network_impact_physics_labels.parquet
    network_impact_physics_labels_report.json
    network_impact_physics_predictions.parquet
    network_impact_physics_surrogate_report.json
    locational_clearing_events.parquet
    locational_clearing_selections.parquet
    locational_clearing_summary.json
  reports/
    digital_twin_build_manifest.json
    mv_lv_transformer_overload_report.json
    canonical/
  semantic/
    nodes.parquet
    edges.parquet
    graph_manifest.json
    profile_north_america.json
    validation_report.json
```

## Build Orchestration

Use `gridalyn twin` as the top-level regeneration entrypoint when rebuilding
the canonical artifacts. The stable contract is centered on:
`instances/default/digital_twin/base`, `instances/default/digital_twin/scenarios`, `instances/default/digital_twin/timeseries`,
`instances/default/digital_twin/models`, `instances/default/digital_twin/flexibility`, `instances/default/digital_twin/semantic`,
`instances/default/digital_twin/reports`, and `instances/default/digital_twin/dashboard/catalog.json`.

Preview the ordered build without writing heavy simulation outputs:

```bash
uv run gridalyn twin build --dry-run --skip-heavy
```

Rebuild the core digital twin:

```bash
uv run gridalyn twin build
```

The first step, `export_base`, reads the topology caches
`pp_net_cache.pkl` and `pg_graph_cache.pkl` from
`instances/default/digital_twin/cache/`. That directory is git-ignored and is
absent on a fresh checkout, so the build fails there with `FileNotFoundError`
until it is populated. Populate it with
`gridalyn.simulation.build_synthetic_network_from_geojson`, passing the cache
directory as `out_dir` and `write_cache=True` — the same call
`examples/tutorials/create_grid_from_real_data.py` makes, pointed at the twin
cache instead of `examples/generated/outputs/`.

Include the Network Impact and clearing scorecard artifacts:

```bash
uv run gridalyn twin build --include-network-impact
```

For fast CI or local checks, combine `--skip-heavy` with
`--include-network-impact`; this skips pandapower-heavy sampling while still
planning the semantic, dashboard, report, and surrogate metadata steps.

Every run writes `instances/default/digital_twin/reports/digital_twin_build_manifest.json` with
the planned/executed steps and canonical downstream artifacts.

## Base Assets

`instances/default/digital_twin/base` describes the static network:

- `buildings.parquet`: one row per building/load instance with `building_id`, `load_id`, `pandapower_load`, location, area, static load, and seeds.
- `building_grid_connectivity.parquet`: maps buildings and loads to load buses, LV clusters, feeder buses, and transformers.
- `grid_buses.parquet`: CIM-like connectivity nodes with voltage, category, location, and service status.
- `grid_lines.parquet`: line assets with terminal buses and electrical parameters.
- `grid_transformers.parquet`: transformer assets with HV/LV buses and nameplate data.
- `metadata.json`: repository-centric model manifest with schema version,
  model version, source adapter, artifact hashes, topology counts, and network
  validation status.

Reusable code should access these tables through the network repository instead
of duplicating topology joins:

```python
from gridalyn.twin import NetworkModelRepository

repo = NetworkModelRepository.from_parquet("instances/default/digital_twin/base")
model = repo.load_model()
integrity = repo.validate_integrity()
```

The same repository is used by platform services such as dashboard catalog
generation so that topology counts, feeder queries, transformer downstream
queries, and validation metadata stay consistent across studies.

Current repository-first consumers include:

- base metadata generation;
- EV scenario generation;
- building model input loading;
- semantic graph generation;
- flexibility provider registry generation;
- dashboard catalog topology summaries.

The base metadata manifest is generated after the Parquet files are written and
is validated by loading those files back through `NetworkModelRepository`. Its
key fields are:

| Field | Meaning |
| --- | --- |
| `schema_version` | Metadata contract version. |
| `model_version_id` | Stable model identifier in the form `model:sha256:<digest>`. |
| `model_version` | Governance object with source system, adapter, source format, artifact hashes, counts, validation status, timestamp, and lineage. |
| `adapter_id` | Stable adapter identifier, currently `synthetic_pandapower`. |
| `source_adapter` | Adapter that produced the model snapshot, currently `SyntheticPandapowerAdapter`. |
| `source_standard` | Source model family, currently `pandapower`. |
| `source_format` | Concrete input format, currently `pandapower-cache`. |
| `adapter_capabilities` | Declared adapter behaviors such as snapshot loading, base export, metadata writing, and validation report writing. |
| `adapter_validation_report` | Validation report emitted by the adapter export. |
| `artifacts` | Path, row count, and SHA-256 for each base Parquet artifact. |
| `validation` | Endpoint and customer-connectivity validation from `NetworkModelRepository`. |

The current base export command is a thin wrapper around
the default `gridalyn.twin.adapters.NetworkAdapterRegistry`, which resolves
`synthetic_pandapower` to
`gridalyn.twin.adapters.SyntheticPandapowerAdapter`. That keeps the synthetic
workflow working while making the source-adapter boundary explicit for future
GIS, CIM, OpenDSS, or DMS imports. Adapter exports also write
`network_adapter_validation_report.json`, which records adapter identity, source
standard, source format, declared capabilities, artifact existence, model
counts, and topology validation results.

Dashboard catalogs read `model_version_id` and `model_version` from
`instances/default/digital_twin/base/metadata.json` when a network repository is available, so
visualized scenarios can be traced back to the exact model snapshot.

The registry also exposes `cim_parquet` through
`gridalyn.twin.adapters.CimParquetAdapter`. This first utility-facing path accepts
CIM-like Parquet source tables and emits the same canonical base snapshot as the
synthetic pandapower path. It is a pragmatic interchange adapter, not a full CIM
RDF/XML importer.

## Building Model Layer

`instances/default/digital_twin/models` turns static building rows into simulation-ready building
entities. It follows a pyCity-style decomposition without introducing a pyCity
runtime dependency:

- `building_models.parquet`: one deterministic model per building with
  archetype, floor area, bus/transformer lineage, thermal parameters, and
  estimated HVAC/base-load capacity.
- `thermal_zones.parquet`: one conditioned thermal zone per building for the
  current simplified profile.
- `device_registry.parquet`: HVAC devices for Soft CLS flexibility and EVSE
  device rows when the source building table already marks an EV instance.
- `end_use_loads.parquet`: heating, cooling, and non-HVAC background load
  estimates.
- `building_model_manifest.json`: profile, counts, inputs, units, and artifact
  paths.
- `models/scenarios/S*_device_registry.parquet`: scenario-specific device
  overlays that attach Soft CLS HVAC devices and Hard CLS EVSEs to building
  models, buses, transformers, providers, and aggregators.
- `models/scenarios/scenario_model_manifest.json`: scenario counts for EVSEs,
  Soft CLS buildings, Hard-only EVs, Soft+Hard overlap, and available capacity.

Generate it directly with:

```bash
uv run gridalyn twin building-models
```

Generate scenario overlays after `asset_registry.parquet` exists:

```bash
uv run gridalyn twin scenario-models
```

The current default profile is `north_america_residential_v1`. It is a compact
North America residential profile intended as a reproducible baseline for
studies, flexibility provider synthesis, and future calibration against measured
or simulated building data.

## Dashboard Catalog

`instances/default/digital_twin/dashboard/catalog.json` is the general-purpose UI contract for the
grid viewer. It is intentionally study-agnostic:

- scenario labels and descriptions;
- Parquet paths for nodes, lines, transformers, and power traces;
- pure grid metrics such as grid peak, load peak, minimum voltage, line loading,
  transformer loading, and overload counts;
- topology counts such as buses, lines, loads, transformers, and timesteps;
- optional extension report paths for study-specific panels.

Generate it with:

```bash
uv run gridalyn dashboard catalog
```

The dashboard should load this catalog first. Other manifests are supporting
diagnostics rather than the primary UI contract.

## Scenarios and Asset Registry

The scenario layer separates study assumptions from physical assets.

- `ev_assignments.parquet` records nested EV adoption by scenario.
- `asset_registry.parquet` joins buildings, EV assignments, and CLS roles.
- `asset_registry_summary.json` gives scenario-level counts used by dashboard and reports.

For S4 in the current generated dataset:

- buildings: `3235`
- EVs: `1294`
- soft CLS participants: `970`
- EVs overlapping soft participants: `389`
- hard-preferred EVs: `905`

## Powerflow Time Series

`instances/default/digital_twin/timeseries` stores scenario-specific simulation results:

- `S*_ev_load.parquet`: EV load by building/load and timestamp.
- `S*_powerflow_nodes.parquet`: bus voltage results.
- `S*_powerflow_lines.parquet`: line loading results.
- `S*_powerflow_transformers.parquet`: transformer loading results.
- `S*_powerflow_power.parquet`: aggregate power exchange.

The dashboard reads these files directly through DuckDB in the browser.

## Flexibility Provider Layer

The provider layer turns scenario roles into network-aware controllable assets:

- `provider_registry.parquet`: one provider row for each Soft CLS building and
  Hard CLS EV, including building, load, bus, feeder, transformer, capacity,
  scenario-device lineage, and cost proxy metadata.
- `network_sensitivity.parquet`: first-pass topology sensitivity between
  providers and transformer constraints.
- `provider_registry_summary.json`: scenario counts and capacity summaries for
  dashboard/report consumers.
- `network_graph_nodes.parquet` and `network_graph_edges.parquet`: GNN-ready
  graph snapshot linking providers, buildings, loads, buses, EVSEs, scenarios,
  and constraints.
- `network_node_features.parquet` and `network_edge_features.parquet`: stable
  integer-indexed feature tables for future tensor conversion.
- `network_impact_training.parquet`: tabular provider-constraint training rows.
- `network_impact_predictions.parquet`: fast predicted deliverability, relief,
  side-effect, and ranking metrics.
- `network_impact_surrogate_report.json`: model scope, counts, and validation
  boundary metadata.
- `network_impact_physics_labels.parquet`: pandapower finite-difference labels
  for provider/timestep/constraint perturbations.
- `network_impact_physics_labels_report.json`: sample counts and aggregate label
  metrics.
- `network_impact_physics_predictions.parquet`: selector-compatible predictions
  from the first physics-backed surrogate.
- `network_impact_physics_surrogate_report.json`: training coverage and
  prediction summary for the physics-backed model.
- `network_impact_catalog.json`: scenario-indexed dashboard manifest pointing
  to the Network Impact JSON reports currently available for each scenario.
- `locational_clearing_events.parquet`: one row per active
  constraint/timestep requirement cleared by the locational market MVP.
- `locational_clearing_selections.parquet`: provider-level selections for each
  event, including selected kW, expected relief, deliverability, rank score, and
  estimated cost.
- `locational_clearing_summary.json`: scenario-level summary for the locational
  clearing run.
- `locational_clearing_dispatch.parquet`: timestep dispatch realized after
  applying selected provider reductions to the S4 building and EV load matrices
  for pandapower replay.

When `instances/default/digital_twin/models/scenarios` exists, providers include:

- `scenario_device_ids`: the scenario HVAC/EVSE device rows behind the provider;
- `device_ids`: base device IDs;
- `building_model_id`: the model-layer building entity;
- `device_types`: `hvac_heating`, `hvac_cooling`, or `evse_l2`;
- `aggregator_id`: the aggregator identity assigned by the scenario overlay.

This keeps clearing, semantic graph queries, and future GNN feature generation
on the same provider/device identity contract.

Generate it with:

```bash
uv run gridalyn market providers \
  --base-dir instances/default/digital_twin/base \
  --scenario-dir instances/default/digital_twin/scenarios \
  --out-dir instances/default/digital_twin/flexibility
```

This layer does not yet replace aggregate clearing engines. It provides the
provider selection substrate needed for locational, constraint-aware clearing.

Generate the GNN-ready impact surrogate:

```bash
uv run gridalyn market surrogate \
  --scenario-id S4 \
  --provider-registry instances/default/digital_twin/flexibility/provider_registry.parquet \
  --sensitivity instances/default/digital_twin/flexibility/network_sensitivity.parquet \
  --out-dir instances/default/digital_twin/flexibility
```

The surrogate is a fast screening layer. Pandapower remains the authority for
validating final dispatch impact on voltage, line loading, and transformer
loading.

Generate the locational clearing MVP:

```bash
uv run gridalyn market locational-clearing \
  --scenario-id S4 \
  --top-constraints 3
```

This derives transformer-specific requirements from overload time series,
selects providers by local deliverability-adjusted offer cost, writes provider
selection Parquet tables, and emits
`instances/default/digital_twin/flexibility/locational_flexibility_clearing_report.json`.

### Retired: the pandapower replay chain

Five commands were removed on 2026-08-06 — `market verify-clearing`,
`market perturbation-samples`, `market verify-network-impact`,
`market shadow-report` and `market scorecard` — together with the five
`gridalyn twin build --include-network-impact` steps that invoked them.

All five read
`instances/default/digital_twin/flexibility/market_dispatch_timeseries.parquet`,
and nothing in this repository has written that file since its only producer,
the `flexibility_cls` study, was retired on 2026-08-03 (archived at the git tag
`archive/flexibility_cls`). They therefore failed with `FileNotFoundError`
wherever they were run. Because their build steps were declared optional, the
build tolerated those failures and still exited 0 — a green exit on a build
missing its verification artifacts.

The locational clearing MVP above still runs and still emits its report; what
is gone is the replay-and-verify layer that consumed a dispatch time series
this repository cannot produce. Reinstating it requires a producer for that
artifact first. See
[Instruction Verification](../development/instruction-verification.md).

Train physics-backed predictions:

```bash
uv run gridalyn market train-physics-surrogate \
  --scenario-id S4
```

Refresh the dashboard manifest after generating or replacing Network Impact
reports:

```bash
uv run gridalyn market network-impact-catalog
```

## Operational Reports

Transformer overload summaries should be published through canonical reports
under `instances/default/digital_twin/reports/canonical`.

Canonical reports include:

- `network_capacity_report.json`
- `scenario_registry_report.json`
- `semantic_graph_report.json`
- `digital_twin_report_manifest.json`

Each canonical report records input file hashes, source artifacts, metrics, and schema version.

## Regeneration

Generate semantic graph artifacts:

```bash
uv run gridalyn semantic build \
  --profile north_america \
  --base-dir instances/default/digital_twin/base \
  --scenario-dir instances/default/digital_twin/scenarios \
  --flexibility-dir instances/default/digital_twin/flexibility \
  --timeseries-dir instances/default/digital_twin/timeseries \
  --out-dir instances/default/digital_twin/semantic
```

When `instances/default/digital_twin/flexibility/provider_registry.parquet` is present, the
semantic graph also indexes the market-management layer: aggregators,
portfolios, providers, offers, and constraint zones. This lets FalkorDB/DuckDB
consumers ask which providers belong to an aggregator, which contract each
provider implements, and which transformer constraint an offer targets without
embedding heavy time-series data in the graph.

Validate semantic graph:

```bash
uv run gridalyn semantic validate \
  --semantic-dir instances/default/digital_twin/semantic \
  --scenario-dir instances/default/digital_twin/scenarios
```

Build canonical digital-twin reports:

```bash
uv run python -m gridalyn.interfaces.reporting.digital_twin
```
