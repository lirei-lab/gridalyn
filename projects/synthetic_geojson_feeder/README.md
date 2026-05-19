# Synthetic GeoJSON Feeder

This project demonstrates the geospatial path into Gridalyn:

1. generate a deterministic set of building-footprint polygons;
2. convert the footprints into a synthetic LV/MV/HV distribution feeder;
3. export pandapower tables, a validation report, and a topology figure.

Run it from the repository root:

```bash
uv run gridalyn project run projects/synthetic_geojson_feeder
uv run gridalyn project status projects/synthetic_geojson_feeder --check-artifacts
```

The demo intentionally uses a tiny 3x3 footprint grid so the full workflow is
fast and easy to inspect. Larger studies should keep the same project contract
but replace `outputs/data/building_footprints.geojson` with footprints from
OpenStreetMap extracts, Microsoft building footprints, or another governed
geospatial source.
