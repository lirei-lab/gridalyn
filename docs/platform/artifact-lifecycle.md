# Artifact Lifecycle

Gridalyn is organized around explicit artifacts. A project should be
reproducible because every stage declares what it reads and what it writes.

## Flow

```text
GeoJSON / configs / project.yaml
        |
        v
synthetic or imported network model
        |
        v
instances/default/digital_twin/base
        |
        +--> instances/default/digital_twin/scenarios
        +--> instances/default/digital_twin/models
        +--> instances/default/digital_twin/timeseries
        +--> instances/default/digital_twin/flexibility
        +--> instances/default/digital_twin/semantic
        |
        v
instances/default/digital_twin/reports and project outputs
        |
        v
dashboard catalogs, validation, and release checks
```

## Canonical Roots

| Root | Purpose |
| --- | --- |
| `instances/default/digital_twin/cache` | Local topology and simulation caches used by platform commands. |
| `instances/default/digital_twin/base` | Static network, building, and connectivity tables. |
| `instances/default/digital_twin/scenarios` | Scenario definitions and asset registries. |
| `instances/default/digital_twin/models` | Building, device, and scenario model overlays. |
| `instances/default/digital_twin/timeseries` | Parquet time-series outputs. |
| `instances/default/digital_twin/flexibility` | Provider registries, market selections, impact models, and operation reports. |
| `instances/default/digital_twin/operations` | Operation catalogs and dispatch/settlement manifests. |
| `instances/default/digital_twin/semantic` | Semantic graph nodes, edges, manifests, and validation reports. |
| `instances/default/digital_twin/dashboard` | Dashboard catalogs and visual metadata. |
| `projects/<name>/outputs` | Project-owned outputs that are not part of the reusable platform state. |

## Rule Of Thumb

If an artifact describes the reusable twin, put it under `instances/default/digital_twin`. If it
is specific to a demo, study, or experiment, put it under the project output
directory and declare it in the project workflow.
