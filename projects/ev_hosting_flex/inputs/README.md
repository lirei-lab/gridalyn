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

## `streets.geojson`

Street network (`drive_service`) around the footprints, pinned so the topology
build does not depend on the day OpenStreetMap was fetched (bd 4os.7). It
supplies the street blocks the LV partition keeps clusters inside and the street
positions transformers are sited on.

- **Written by:** `tools/snapshot_streets.py --footprints inputs/buildings.geojson --out inputs/streets.geojson`
  (padding 0.012 deg, so blocks at the extent edge close)
- **Declared in:** `synthetic_network_config.json` → `topology.street_layer`,
  with its SHA-256. The build refuses the file if the digest no longer matches,
  and a deliberate update changes the config hash the topology cache keys on.
- **Attribution:** contains data © OpenStreetMap contributors, available under
  the Open Database License (ODbL) 1.0, https://www.openstreetmap.org/copyright
