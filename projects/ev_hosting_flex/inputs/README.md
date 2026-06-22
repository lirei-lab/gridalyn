# Project inputs

## `buildings.geojson`

Project-local copy of the clipped Trois-Rivieres building footprints used to
synthesize the `ev_hosting_flex` topology cache (decision **D-03**).

- **Source:** `examples/tutorials/data/buildings_inside_polygon.geojson`
- **Format:** GeoJSON `FeatureCollection`

Holding the footprints project-local (rather than reaching into the shared SDK
dataset via `get_dataset_path(...)`) pins this study's twin to a fixed input.
The topology-cache stage (`scripts/pipeline/prepare_topology_cache.py`) records
the source file's **SHA-256** in `outputs/cache/topology_cache_manifest.json`
and `outputs/cache/building_footprint_validation_report.json`, so the lineage
from this byte-exact input to every downstream artifact is auditable.
