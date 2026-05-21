# Synthetic GeoJSON Feeder

`projects/synthetic_geojson_feeder` demonstrates Gridalyn's geospatial route
from building-footprint GeoJSON to a synthetic distribution feeder.

## Why This Demo Exists

Gridalyn is not only a collection of pandapower examples. One of its central
capabilities is creating governed synthetic network models from geospatial
inputs. This demo gives that capability a small, reproducible project:

```text
building footprints -> synthetic LV/MV/HV topology -> pandapower model -> validation report
```

The demo uses generated footprints so it can run without downloading external
data. Larger projects can replace that generated input with governed extracts
from OpenStreetMap, Microsoft building footprints, municipal cadastral data, or
utility GIS exports.

## Run It

```bash
uv run gridalyn project run projects/synthetic_geojson_feeder
uv run gridalyn project status projects/synthetic_geojson_feeder --check-artifacts
```

Expected artifacts:

```text
projects/synthetic_geojson_feeder/outputs/data/building_footprints.geojson
projects/synthetic_geojson_feeder/outputs/data/buses.csv
projects/synthetic_geojson_feeder/outputs/data/lines.csv
projects/synthetic_geojson_feeder/outputs/data/loads.csv
projects/synthetic_geojson_feeder/outputs/reports/building_footprints_report.json
projects/synthetic_geojson_feeder/outputs/reports/synthetic_network_validation_report.json
projects/synthetic_geojson_feeder/outputs/reports/synthetic_geojson_feeder_report.json
projects/synthetic_geojson_feeder/outputs/figures/synthetic_feeder_topology.png
projects/synthetic_geojson_feeder/outputs/manifests/project_run_manifest.json
```

## Workflow

| Stage | Purpose |
| --- | --- |
| `prepare_workspace` | Creates the project output folders. |
| `generate_building_footprints` | Creates a deterministic 3x3 GeoJSON footprint set and writes an input report. |
| `build_synthetic_feeder` | Builds the synthetic network, runs pandapower, exports tables, writes reports, and plots topology. |

## Platform APIs Used

| API | Role |
| --- | --- |
| `gridalyn.twin.adapters.geojson.FakeGeoJSONGenerator` | Creates deterministic demo footprints. |
| `gridalyn.twin.adapters.geojson.validate_geojson` | Checks the generated GeoJSON input. |
| `gridalyn.simulation.build_synthetic_network_from_geojson` | Converts footprints and config into a graph, pandapower network, and validation report. |
| `gridalyn.foundation.write_report` | Writes platform-standard JSON reports. |

## Input Configuration

The feeder sizing contract is in:

```text
projects/synthetic_geojson_feeder/inputs/synthetic_network_config.json
```

It declares load assumptions, voltage levels, line standard types, transformer
types, transformer capacities, and diversity factors. For a new utility-style
project, start by changing this file and then replacing the footprint source.

## What To Learn

This demo is the bridge between tutorials and real project generation:

- GeoJSON is treated as a governed input, not hidden test data.
- Network generation writes a validation report.
- The pandapower model remains a simulation artifact, while the project report
  gives stable metrics for automation and documentation.
- The workflow can be reused with larger geospatial datasets without changing
  the project contract.
