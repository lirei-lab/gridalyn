# Tutorial Data Usage

`examples/tutorials/data/` contains small, source-controlled inputs for
offline tutorials and tests. Generated tutorial outputs belong under
`examples/generated/outputs/`, which is ignored by Git.

## Included Data

| Path | Purpose |
| --- | --- |
| `minimal/` | Tiny contract dataset used by smoke tests and introductory tutorials. |
| `example_buildings.geojson` | Small building-footprint sample for clipping examples. Covers the CLI polygon smoke test and the Trois-Rivieres tutorial wrapper. |
| `buildings_inside_polygon.geojson` | Clipped Trois-Rivieres footprint sample used by `projects/flexibility_cls`. |

Use the dataset helper when code needs a stable path:

```python
from gridalyn.foundation.data import get_dataset_path

path = get_dataset_path("buildings_inside_polygon.geojson")
```

Full city-scale building exports, HDF5 simulation dumps, and downloaded OSM or
Microsoft footprint partitions are intentionally not tracked. Regenerate them
into `examples/generated/outputs/`, `projects/<project>/inputs/`, or external
release artifacts with explicit lineage.
