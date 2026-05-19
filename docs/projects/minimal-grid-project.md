# Minimal Grid Project

`projects/minimal_grid_project` is the smallest complete Gridalyn project. It
exists to teach the project contract before a user opens a benchmark feeder,
geospatial pipeline, market workflow, or advanced control demo.

## Why This Demo Exists

Large workflows are useful after the user understands the platform. This demo
keeps the first experience deliberately small:

- one `project.yaml`;
- one `workflow.yaml`;
- one script;
- one pandapower AC power-flow run;
- three CSV data tables;
- one JSON report;
- one figure;
- one run manifest.

It is the recommended starting point when creating a new project by hand.

## Run It

```bash
uv run gridalyn project run projects/minimal_grid_project
uv run gridalyn project status projects/minimal_grid_project --check-artifacts
```

Expected artifacts:

```text
projects/minimal_grid_project/outputs/data/buses.csv
projects/minimal_grid_project/outputs/data/lines.csv
projects/minimal_grid_project/outputs/data/loads.csv
projects/minimal_grid_project/outputs/reports/minimal_grid_report.json
projects/minimal_grid_project/outputs/figures/minimal_voltage_profile.png
projects/minimal_grid_project/outputs/manifests/project_run_manifest.json
```

## Workflow

| Stage | Purpose |
| --- | --- |
| `prepare_workspace` | Creates the project output folders. |
| `run_minimal_powerflow` | Builds a five-bus radial feeder, runs pandapower, exports tables, writes a report, and plots voltage. |

## What To Learn

This demo shows the core Gridalyn loop:

```text
project contract -> workflow stage -> simulation -> artifacts -> report -> validation
```

Use it when you want to understand the mechanics without studying market
clearing, semantic graph generation, stochastic profiles, or geospatial
network synthesis.

## How To Extend It

| Goal | First file to edit |
| --- | --- |
| Change loads or topology | `scripts/run_minimal_powerflow.py` |
| Add another report | `project.yaml` and `workflow.yaml` |
| Add operation records | `outputs/operations/` and a new workflow stage |
| Promote reusable logic | Move it from `projects/minimal_grid_project/scripts/` into `gridalyn/` |

Project scripts should bind concrete paths and parameters. Reusable platform
logic belongs in the SDK package.
