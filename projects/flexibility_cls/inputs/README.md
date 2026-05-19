# Flexibility CLS Inputs

This folder is the project-local input boundary for replacing the default
building-footprint source used to synthesize the network topology.

The committed workflow uses the lightweight demo footprint declared in
`project.yaml`:

```text
examples/tutorials/data/buildings_inside_polygon.geojson
```

For a custom run, place or generate:

```text
projects/flexibility_cls/inputs/buildings.geojson
```

## Expected Contract

- Format: GeoJSON `FeatureCollection`.
- CRS: WGS84 / EPSG:4326 preferred.
- Geometry: `Polygon` or `MultiPolygon` building footprints.
- Scope: already clipped to the study boundary.
- Source lineage: record whether the file came from OSMnx, Microsoft Global ML
  Building Footprints, utility GIS, or another source.
- License: verify the source license before publishing derived artifacts.

## Prepare From OSMnx

```bash
uv run gridalyn twin download-osm-buildings \
  --polygon-file configs/geography/tr01.json \
  --output-file projects/flexibility_cls/inputs/buildings.geojson
```

## Prepare From Microsoft Building Footprints

```bash
uv run gridalyn twin prepare-microsoft-buildings \
  --input-file /path/to/microsoft-partition.csv.gz \
  --polygon-file configs/geography/tr01.json \
  --output-file projects/flexibility_cls/inputs/buildings.geojson
```

## Rebuild The Topology Cache

```bash
uv run python projects/flexibility_cls/scripts/pipeline/prepare_topology_cache.py \
  --input-file projects/flexibility_cls/inputs/buildings.geojson \
  --force-rebuild
```

The stage writes:

```text
projects/flexibility_cls/outputs/cache/building_footprint_validation_report.json
projects/flexibility_cls/outputs/cache/topology_cache_manifest.json
```

Do not commit large source downloads or generated project outputs.
