# Minimal Grid Project

The smallest complete Gridalyn study. It exists to teach the project contract
before anyone opens a benchmark feeder, a geospatial pipeline, a market
workflow or an advanced control demo — and it is the folder to copy when
starting a new study by hand.

## What this study asks

Nothing, deliberately. Every other study under `projects/` asks a research
question; this one asks only whether the platform contract is legible. It
keeps the first experience small enough to hold in one reading: one
`project.yaml`, one `workflow.yaml`, one script, one Gridalyn-managed AC power
flow, three CSV tables, one JSON report, one figure, one run manifest.

Even at this size it uses the platform's real load generators rather than a
shortcut. The `loadGeneration` block in `project.yaml` declares a seeded
synthetic residential fleet; the declared `loadsMw` anchor the system total
while the generated coincident-peak snapshot diversifies the per-bus shares.

## Running it

```bash
uv run gridalyn project run projects/minimal_grid_project
uv run gridalyn project status projects/minimal_grid_project --check-artifacts
```

| Stage | Purpose |
| --- | --- |
| `prepare_workspace` | Creates the project output folders. |
| `run_minimal_powerflow` | Loads the five-bus feeder contract from `project.yaml`, runs the standard power-flow helper, exports tables, writes a report, and plots voltage. |

## What it produces

```text
projects/minimal_grid_project/outputs/data/buses.csv
projects/minimal_grid_project/outputs/data/lines.csv
projects/minimal_grid_project/outputs/data/loads.csv
projects/minimal_grid_project/outputs/reports/minimal_grid_report.json
projects/minimal_grid_project/outputs/figures/minimal_voltage_profile.png
projects/minimal_grid_project/outputs/manifests/project_run_manifest.json
```

## How it is verified

`gridalyn project status --check-artifacts` above is the check: it reports
whether every declared artifact and report was produced. The study also
carries `baselines/results_baseline.json`, so `gridalyn project regression`
answers whether its numbers moved, and it runs end to end in CI as one of the
six governed fixtures.

## Scope and limits

This study demonstrates the loop, not a result. Its five-bus feeder is not a
model of anything, its numbers are not calibrated against measurement, and no
finding should be quoted from it. For what the platform can and cannot claim
about generated loads, see [Assets](../../docs/components/assets.md).

## Where this sits

It is the concrete form of the loop the platform is built around:

```text
project contract -> workflow stage -> simulation -> artifacts -> report -> validation
```

To extend it, edit inward from the contract:

| Goal | First file to edit |
| --- | --- |
| Change loads or topology | `project.yaml` |
| Add another report | `project.yaml` and `workflow.yaml` |
| Add operation records | `outputs/operations/` and a new workflow stage |
| Promote reusable logic | Move it from `scripts/` into `gridalyn/` |

Project scripts bind concrete paths and parameters; reusable platform logic
belongs in the SDK package. The larger studies under `projects/` are this same
shape with a research question attached.
