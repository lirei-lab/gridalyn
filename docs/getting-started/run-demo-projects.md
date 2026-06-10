# Run Demo Projects

Gridalyn projects are reproducible workspaces. Each project owns a
`project.yaml`, a `workflow.yaml`, input references, generated outputs,
manifests, reports, and validation checks. The same commands work for compact
demos and larger studies.

The public documentation should teach the project pattern, not anchor the
platform to one unpublished study. Use the small demos first, then move to the
larger flexibility workflow only when you want an end-to-end operations example.

## Recommended Order

| Project | Why run it first |
| --- | --- |
| `projects/minimal_grid_project` | Fastest smoke test for project contracts, reports, and figures. |
| `projects/ieee_33_bus_demo` | Familiar benchmark feeder with planning-style outputs. |
| `projects/synthetic_geojson_feeder` | Shows the GeoJSON-to-network generation path. |
| `projects/prosumer_battery_market` | Demonstrates prosumer assets, forecasts, and market clearing. |
| `projects/der_voltage_optimization` | Demonstrates CVXPY plus pandapower verification. |
| `projects/rl_voltage_control_lightsim` | Demonstrates a Gridalyn voltage-control environment backed by LightSim2Grid. |
| `projects/flexibility_cls` | Larger flexibility/CLS workflow for operations, clearing, verification, and reports. |

## Common Commands

Validate a project contract:

```bash
uv run gridalyn project validate projects/minimal_grid_project --check-artifacts
```

Inspect its planned stages:

```bash
uv run gridalyn project plan projects/minimal_grid_project
```

Run it (per-stage progress streams to the terminal):

```bash
uv run gridalyn project run projects/minimal_grid_project
```

While iterating on one stage, run only that stage and its dependencies:

```bash
uv run gridalyn project run projects/minimal_grid_project --stage run_minimal_powerflow
```

Check outputs and required artifacts:

```bash
uv run gridalyn project status projects/minimal_grid_project --check-artifacts
```

Run the publication-style verification ladder:

```bash
uv run gridalyn project verify projects/minimal_grid_project
```

Verify all governed demos:

```bash
uv run gridalyn project verify-all
```

Check pinned result metrics against the project's regression baseline (every
demo ships one under `baselines/results_baseline.json`):

```bash
uv run gridalyn project regression projects/minimal_grid_project
```

If a command fails with an import error, `uv run gridalyn doctor` shows which
optional capabilities are installed; domain CLIs also print the exact
`pip install "gridalyn[<extra>]"` command they need.

## Project Outputs

Most projects follow this output layout:

```text
projects/<name>/outputs/data/
projects/<name>/outputs/json/
projects/<name>/outputs/figures/
projects/<name>/outputs/reports/
projects/<name>/outputs/manifests/
projects/<name>/outputs/operations/
```

Not every project uses every folder. Small demos may only write reports and one
figure; operations demos usually write `outputs/operations/` as well.

## Larger Flexibility Workflow

The Flexibility CLS project is a comprehensive technical demo. It starts from
project-declared inputs, builds a synthetic topology cache, generates
stochastic profiles, computes dynamic thermal limits, clears flexibility,
validates selected actions with pandapower, writes figures, materializes
operation artifacts, and produces canonical reports.

Run it only when you need the full stack:

```bash
uv run gridalyn project run projects/flexibility_cls
uv run gridalyn project verify projects/flexibility_cls
```

Its generated artifacts live under:

```text
projects/flexibility_cls/outputs/
```

The project remains useful as a technical stress test, but it is not the
identity of Gridalyn.

## Synthetic Network Inputs

Projects that build synthetic networks can start from building-footprint
GeoJSON. The default tutorial path is:

```text
examples/tutorials/data/buildings_inside_polygon.geojson
```

To prepare footprints from OpenStreetMap or Microsoft Building Footprints, see
[Synthetic Networks From GeoJSON](../tutorials/synthetic-network-from-geojson.md).

## Next Reading

- [Demo Projects](../projects/overview.md)
- [Project Model](../projects/project-model.md)
- [Project Template Guide](../projects/template-guide.md)
- [Workflow YAML Reference](../workflows/workflow-yaml-reference.md)
- [Reproducibility Checklist](reproducibility.md)
