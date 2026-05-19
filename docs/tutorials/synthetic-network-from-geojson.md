# Synthetic Networks From GeoJSON

Gridalyn can build a synthetic distribution network from building-footprint
GeoJSON. This path is useful when a utility-grade GIS model is unavailable but
you still need a reproducible topology for studies, demos, or early digital
twin development.

## Data Sources

Two footprint sources are supported by the examples:

| Source | How Gridalyn uses it | Notes |
| --- | --- | --- |
| OpenStreetMap through OSMnx | `BuildingDownloader` queries OSM features with `building=True` inside a polygon and writes a local GeoJSON. | OSMnx returns a GeoPandas GeoDataFrame from the OpenStreetMap Overpass API. The OSM `building=*` tag describes physical buildings and includes broad categories, so inspect local data quality before treating tags as customer classes. |
| Microsoft Global ML Building Footprints | `prepare_microsoft_building_footprints.py` converts a local line-delimited GeoJSON partition to regular clipped GeoJSON. | Microsoft publishes open building footprints derived from imagery under CDLA Permissive 2.0. Many partitions are `.csv.gz` files whose contents are GeoJSON lines, so convert and clip them before using them as study inputs. |

The repository does not track heavyweight source downloads. Keep raw OSM or
Microsoft source files outside Git, then write filtered outputs under a project
input folder or `examples/generated/outputs/` for tutorial work.

## Flow

```mermaid
flowchart LR
    osm[OSMnx / OSM buildings] --> raw[Raw building footprints]
    ms[Microsoft footprint partition] --> raw
    raw --> clip[Clip to study polygon]
    clip --> geojson[Building GeoJSON]
    geojson --> graph[PowerGridGraph]
    graph --> pp[pandapower network]
    pp --> twin[Digital twin base artifacts]
```

The canonical footprint preparation entry point is `gridalyn.twin.adapters`.
The canonical network-generation entry point is
`gridalyn.assets.build_synthetic_network_from_geojson`. Historical namespaces
such as `gridalyn.geoprocess` and `gridalyn.modeling` remain as compatibility
layers only.

## Project API

Projects should call the SDK builder instead of duplicating the tutorial script
steps:

```python
from pathlib import Path

from gridalyn.assets import build_synthetic_network_from_geojson

result = build_synthetic_network_from_geojson(
    footprints_path=Path("projects/my_project/inputs/buildings.geojson"),
    config_path=Path("configs/grid/config.json"),
    out_dir=Path("projects/my_project/outputs/cache"),
    clustering_crs="auto",
    write_cache=True,
    run_powerflow=True,
)
```

The function returns:

| Field | Meaning |
| --- | --- |
| `power_grid` | The generated `PowerGridGraph` with LV/MV/HV graph layers. |
| `net` | The generated pandapower network. |
| `validation_report` | Counts, CRS lineage, source hashes, topology checks, and optional power-flow convergence. |
| `report_path` | Path to `synthetic_network_validation_report.json` when `out_dir` is provided. |

Use `clustering_crs="auto"` for normal GeoJSON inputs. It estimates a local
metric CRS for K-Means and MST distances while preserving longitude/latitude on
graph nodes for maps and digital-twin geodata.

## Offline Smoke Test

Run the synthetic generator example:

```bash
MPLCONFIGDIR=/tmp/matplotlib-cache \
uv run python examples/tutorials/basic_grid_creation.py
```

It generates fake building footprints, creates LV/MV/HV graphs, and writes local
inspection maps under `examples/generated/outputs/`.

Run the bundled real-footprint example:

```bash
MPLCONFIGDIR=/tmp/matplotlib-cache \
uv run python examples/tutorials/create_grid_from_real_data.py
```

It reads the packaged Trois-Rivieres tutorial footprint sample, builds a
pandapower model, runs diagnostics, and writes generated tutorial artifacts
under `examples/generated/outputs/`.

## Clip Existing Footprints

Use this when you already have GeoJSON from OSMnx, Microsoft after conversion,
or another source:

```bash
MPLCONFIGDIR=/tmp/matplotlib-cache \
uv run gridalyn twin clip-buildings \
  --buildings-file examples/tutorials/data/buildings_tr.json \
  --polygon-file configs/geography/tr01.json \
  --output-file examples/generated/outputs/buildings_inside_polygon.geojson
```

You can pass a custom polygon file:

```bash
uv run gridalyn twin clip-buildings \
  --buildings-file path/to/buildings.geojson \
  --polygon-file configs/geography/tr01.json \
  --output-file projects/my_project/inputs/buildings.geojson
```

The polygon file can be one of:

- a JSON file with `polygon_coordinates`;
- a GeoJSON `Polygon`;
- a GeoJSON `Feature` whose geometry is a `Polygon`.

## Download From OSMnx

Use this only when you want to query OpenStreetMap through Overpass:

```bash
uv run gridalyn twin download-osm-buildings \
  --polygon-file configs/geography/tr01.json \
  --output-file examples/generated/outputs/osmnx_buildings.geojson
```

Network access and Overpass availability determine whether this command
succeeds. For reproducible projects, commit a small input manifest and keep the
raw downloaded source outside Git.

## Prepare Microsoft Building Footprints

After downloading the relevant Microsoft partition locally, convert and clip it:

```bash
uv run gridalyn twin prepare-microsoft-buildings \
  --input-file /path/to/microsoft-partition.csv.gz \
  --polygon-file configs/geography/tr01.json \
  --output-file projects/my_project/inputs/buildings.geojson
```

Use `--limit 1000` for a fast smoke test on a large partition.

## Quality Checks

Before using footprints as digital-twin inputs:

1. Filter to `Polygon` and `MultiPolygon` geometries.
2. Validate geometries and repair invalid polygons.
3. Clip to the study boundary.
4. Inspect the footprint count and map.
5. Confirm CRS is WGS84 or explicitly projected before area-sensitive work.
6. Store source lineage in the project manifest.

## References

- [OSMnx features module](https://osmnx.readthedocs.io/en/stable/getting-started.html#urban-amenities)
- [OSMnx `features_from_polygon`](https://osmnx.readthedocs.io/en/stable/user-reference.html#osmnx.features.features_from_polygon)
- [OpenStreetMap building tags](https://wiki.openstreetmap.org/wiki/Buildings)
- [Microsoft Global ML Building Footprints](https://github.com/microsoft/GlobalMLBuildingFootprints)
