# Examples

`examples/` is for tutorials and exploratory demos only. The directory is
organized so a new user can distinguish learning material from generated local
state.

Stable platform commands live under `gridalyn.interfaces.cli`:

```bash
uv run python -m gridalyn.interfaces.cli.digital_twin build --dry-run
uv run python -m gridalyn.interfaces.cli.flexibility locational-clearing --scenario-id S4
uv run python -m gridalyn.interfaces.cli.semantic build
uv run python -m gridalyn.interfaces.cli.dashboard catalog
```

The project also exposes installed script entrypoints:

```bash
uv run gridalyn-dt build --dry-run
uv run gridalyn-flex verify-clearing \
  --scenario-id S4 \
  --cache-dir projects/ev_hosting_flex/outputs/cache \
  --market-dispatch-path projects/ev_hosting_flex/outputs/data/market_dispatch_timeseries.parquet
uv run gridalyn-semantic validate
uv run gridalyn-dashboard catalog
```

The `verify-clearing` smoke command assumes `projects/ev_hosting_flex` has been
run. The shorter `gridalyn-flex verify-clearing --scenario-id S4` form targets a
materialized `instances/default/digital_twin/` instance.

## Tutorial Scripts

Keep new educational examples under `examples/tutorials/` when they demonstrate
how to use the package. Tutorial scripts should call public Gridalyn facades
such as `gridalyn.simulation`, `gridalyn.assets`, `gridalyn.twin`, and
`gridalyn.operations`; low-level graph builders and runner internals belong in
the SDK and tests, not in public tutorials:

- `tutorials/basic_grid_creation.py`
- `tutorials/create_grid_from_real_data.py`
- `tutorials/demo_with_power_flow.py`
- `tutorials/generate_and_visualize_grid.py`
- `tutorials/create_grid_with_datagen_serial.py`
- `tutorials/evaluate_transformer_diversity.py`

Data acquisition examples live under `examples/data_acquisition/`:

- `download_building_data_osmnx.py`: queries OpenStreetMap building footprints
  with OSMnx and writes GeoJSON.
- `filter_buildings_by_polygon.py`: clips existing GeoJSON footprints to a
  study polygon without network access.
- `prepare_microsoft_building_footprints.py`: converts a local Microsoft Global
  ML Building Footprints GeoJSON-lines partition into regular clipped GeoJSON.

See the docs tutorial
`docs/tutorials/synthetic-network-from-geojson.md` for the recommended
OSMnx/Microsoft workflow.

## Generated State

`examples/generated/cache` and `examples/generated/outputs` are local generated
state. They are not source files and should not be committed. Generated Python
caches such as `__pycache__` can be removed at any time.

Reusable grid and geography configurations live under top-level `configs/`.
Tutorials may read those configs, but `examples/` should not own operational
configuration for projects or digital-twin workflows.

## Directory Map

```text
examples/
  tutorials/          # readable learning examples
  data_acquisition/   # OSMNX/building download and filtering examples
  generated/          # generated example outputs and request caches
```

Archived/debug examples are intentionally kept out of the public source tree.
If you need to experiment with PNNL CIM-Graph/CIMantic Graphs, install the
optional integration first:

```bash
uv sync --extra cim
```

## Contributing

When adding a new operational command, add it under `gridalyn.interfaces.cli` or
a workflow module. Do not add production wrappers under `examples/`.
