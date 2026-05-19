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
digital_twin/base
        |
        +--> digital_twin/scenarios
        +--> digital_twin/models
        +--> digital_twin/timeseries
        +--> digital_twin/flexibility
        +--> digital_twin/semantic
        |
        v
digital_twin/reports and project outputs
        |
        v
dashboard catalogs, validation, and release checks
```

## Canonical Roots

| Root | Purpose |
| --- | --- |
| `digital_twin/cache` | Local topology and simulation caches used by platform commands. |
| `digital_twin/base` | Static network, building, and connectivity tables. |
| `digital_twin/scenarios` | Scenario definitions and asset registries. |
| `digital_twin/models` | Building, device, and scenario model overlays. |
| `digital_twin/timeseries` | Parquet time-series outputs. |
| `digital_twin/flexibility` | Provider registries, market selections, impact models, and operation reports. |
| `digital_twin/operations` | Operation catalogs and dispatch/settlement manifests. |
| `digital_twin/semantic` | Semantic graph nodes, edges, manifests, and validation reports. |
| `digital_twin/dashboard` | Dashboard catalogs and visual metadata. |
| `projects/<name>/outputs` | Project-owned outputs that are not part of the reusable platform state. |

## Rule Of Thumb

If an artifact describes the reusable twin, put it under `digital_twin`. If it
is specific to a demo, manuscript, or experiment, put it under the project
output directory and declare it in the project workflow.

