# Minimal Grid Project

This is the smallest complete Gridalyn project. It is meant for developers who
want to understand the platform contract before opening the larger demos.

The workflow builds a five-bus radial feeder, runs one AC power flow, writes
CSV tables, creates one JSON report, and saves one voltage-profile figure.

Even this minimal project uses the platform load generators: the
`loadGeneration` block in `project.yaml` declares a seeded synthetic
residential fleet, and the declared `loadsMw` anchor the system total while
the generated coincident-peak snapshot diversifies the per-bus shares.

Run it from the repository root:

```bash
uv run gridalyn project run projects/minimal_grid_project
uv run gridalyn project status projects/minimal_grid_project --check-artifacts
```

Use this project as the first template when creating a new study. Copy the
folder, rename the project, then replace the single script with domain-specific
logic while keeping the same `project.yaml`, `workflow.yaml`, report, and
artifact structure.

---

<!-- Merged from the former docs/projects/minimal-grid-project.md. The published
documentation now covers the project CONTRACT in general; per-project
detail lives with the project. -->

`projects/minimal_grid_project` is the smallest complete Gridalyn project. It
exists to teach the project contract before a user opens a benchmark feeder,
geospatial pipeline, market workflow, or advanced control demo.

## Why This Demo Exists

Large workflows are useful after the user understands the platform. This demo
keeps the first experience deliberately small:

- one `project.yaml`;
- one `workflow.yaml`;
- one script;
- one Gridalyn-managed AC power-flow run;
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
| `run_minimal_powerflow` | Loads the five-bus feeder contract from `project.yaml`, runs the standard power-flow helper, exports tables, writes a report, and plots voltage. |

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
| Change loads or topology | `project.yaml` |
| Add another report | `project.yaml` and `workflow.yaml` |
| Add operation records | `outputs/operations/` and a new workflow stage |
| Promote reusable logic | Move it from `projects/minimal_grid_project/scripts/` into `gridalyn/` |

Project scripts should bind concrete paths and parameters. Reusable platform
logic belongs in the SDK package.
