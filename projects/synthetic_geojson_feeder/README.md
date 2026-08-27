# Synthetic GeoJSON Feeder

The geospatial route into Gridalyn, as a small governed study: generate
building-footprint polygons, convert them into a synthetic LV/MV/HV
distribution feeder, and export pandapower tables, a validation report and a
topology figure.

## What this study asks

Whether a network model can be *generated* from geospatial input rather than
declared by hand, and still be governed. The platform is not a collection of
pandapower examples; building synthetic networks from geospatial data is one of
its central capabilities, and this study gives that capability a reproducible
shape:

```text
building footprints -> synthetic LV/MV/HV topology -> pandapower model -> validation report
```

The footprints are generated rather than downloaded so the study runs with no
external data. Larger projects keep the same contract and swap the input for
governed extracts — OpenStreetMap, Microsoft building footprints, municipal
cadastre or utility GIS.

## Running it

```bash
uv run gridalyn project run projects/synthetic_geojson_feeder
uv run gridalyn project status projects/synthetic_geojson_feeder --check-artifacts
```

| Stage | Purpose |
| --- | --- |
| `prepare_workspace` | Creates the project output folders. |
| `generate_building_footprints` | Creates a deterministic 3x3 GeoJSON footprint set and writes an input report. |
| `build_synthetic_feeder` | Builds the synthetic network, runs pandapower, exports tables, writes reports, and plots topology. |
| `export_twin_network_model` | Exports the generated network model to the twin. |

The feeder sizing contract lives in
`inputs/synthetic_network_config.json` — load assumptions, voltage levels, line
standard types, transformer types and capacities, diversity factors. For a new
utility-style project, change that file first and replace the footprint source
second.

## What it produces

```text
outputs/data/building_footprints.geojson
outputs/data/buses.csv
outputs/data/lines.csv
outputs/data/loads.csv
outputs/reports/building_footprints_report.json
outputs/reports/synthetic_network_validation_report.json
outputs/reports/synthetic_geojson_feeder_report.json
outputs/figures/synthetic_feeder_topology.png
outputs/manifests/project_run_manifest.json
```

## How it is verified

Network generation writes its own validation report rather than being trusted:
`synthetic_network_validation_report.json` is an artifact of the build stage,
not an afterthought. On top of that,
`gridalyn project status --check-artifacts` confirms every declared artifact
appeared, `gridalyn project regression` compares against
`baselines/results_baseline.json`, and the study runs end to end in CI as one
of the six governed fixtures.

## Scope and limits

The 3x3 footprint grid is deliberately tiny, so the whole workflow is fast and
inspectable. Nothing about the resulting feeder is a model of a real place, and
its sizing follows the config's diversity assumptions rather than a measured
stock. What transfers to a real study is the contract, not the numbers.

## Where this sits

It is the clearest example of treating an external input as *governed*: the
GeoJSON is a declared project input with its own report, not hidden test data.
It builds on [Twin](../../docs/components/twin.md) for the GeoJSON adapters and
on [Simulation](../../docs/components/simulation.md) for
`build_synthetic_network_from_geojson`, and writes its reports through
[Foundation](../../docs/components/foundation.md)'s report contract.

| API | Role |
| --- | --- |
| `gridalyn.twin.adapters.geojson.FakeGeoJSONGenerator` | Creates deterministic demo footprints. |
| `gridalyn.twin.adapters.geojson.validate_geojson` | Checks the generated GeoJSON input. |
| `gridalyn.simulation.build_synthetic_network_from_geojson` | Converts footprints and config into a graph, pandapower network, and validation report. |
| `gridalyn.foundation.write_report` | Writes platform-standard JSON reports. |
