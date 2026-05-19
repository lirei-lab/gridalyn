# Examples

`examples/` is for tutorials and exploratory demos only. The directory is
organized so a new user can distinguish learning material from compatibility
wrappers and generated state.

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
uv run gridalyn-flex verify-clearing --scenario-id S4
uv run gridalyn-semantic validate
uv run gridalyn-dashboard catalog
```

## Tutorial Scripts

Keep new educational examples under `examples/tutorials/` when they demonstrate
how to use the package:

- `tutorials/basic_grid_creation.py`
- `tutorials/create_grid_from_real_data.py`
- `tutorials/demo_with_power_flow.py`
- `tutorials/generate_and_visualize_grid.py`

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

## Compatibility Scripts

`examples/compat/` contains thin wrappers only. They preserve older script paths
while delegating operational logic to `gridalyn.workflows.scripts` or to a
stable workflow module. New automation should use the CLI modules above instead
of calling these files directly.

When a production script is migrated, its reusable implementation should live
under `gridalyn.workflows`. For example,
`generate_digital_twin_ev_scenarios.py`,
`generate_digital_twin_ev_timeseries.py`, and
`generate_locational_clearing_verification_report.py` are now wrappers around
workflow modules.

Compatibility wrappers should stay small enough to audit at a glance. The test
suite enforces this boundary so `examples/compat` does not become a parallel
production API.

Examples of commands being migrated:

- digital twin artifact generation;
- EV scenario and timeseries generation;
- semantic graph generation and validation;
- flexibility provider, locational clearing, and network impact workflows;
- dashboard catalog generation.

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
  compat/             # temporary wrappers for old production script paths
  generated/          # generated example outputs and request caches
```

Archived/debug examples are intentionally kept out of the public source tree.
If you need to experiment with PNNL CIM-Graph/CIMantic Graphs, install the
optional integration first:

```bash
uv sync --extra cim
```

## Contributing

When adding a new operational command, add it under `gridalyn.interfaces.cli` or a workflow
module first. Add a wrapper in `examples/` only if backwards compatibility is
needed.
