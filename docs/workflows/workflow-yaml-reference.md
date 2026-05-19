# Workflow YAML Reference

The project and workflow files use a small declarative schema inspired by
Kubernetes-style resources. The goal is readability, stable paths, and simple
automation rather than a full external workflow engine.

## Project Resource

```yaml
apiVersion: gridalyn.io/v1alpha1
kind: StudyProject
metadata:
  name: minimal_grid_project
  version: 0.1.0
  description: Minimal Gridalyn project.
spec:
  pathBase: repo
  inputs: {}
  artifacts: {}
  workflow:
    file: projects/minimal_grid_project/workflow.yaml
  validation:
    requiredReports: []
    requiredFigures: []
```

### Fields

| Field | Required | Meaning |
| --- | --- | --- |
| `apiVersion` | yes | Version of the Gridalyn project resource schema. |
| `kind` | yes | Must be `StudyProject`. |
| `metadata.name` | yes | Stable project identifier. |
| `metadata.version` | recommended | Project contract version. |
| `spec.pathBase` | recommended | `repo` resolves paths from repository root; default behavior may resolve from the project folder. |
| `spec.inputs` | yes | Raw geography, grid configuration, external datasets, and assumptions. |
| `spec.artifacts` | yes | Canonical artifact locations. |
| `spec.workflow.file` | yes | Workflow resource path. |
| `spec.validation.requiredReports` | recommended | Report JSON files that must exist and satisfy the report contract. |
| `spec.validation.requiredFigures` | recommended | Figures that must exist and be non-empty. |

## Workflow Resource

```yaml
apiVersion: gridalyn.io/v1alpha1
kind: Workflow
metadata:
  name: minimal_grid_project
spec:
  stages:
    - id: prepare_workspace
      command: uv run python projects/minimal_grid_project/scripts/prepare_workspace.py
      outputs:
        - projects/minimal_grid_project/outputs/reports

    - id: run_powerflow
      needs: [prepare_workspace]
      command: uv run python projects/minimal_grid_project/scripts/run_powerflow.py
      inputs: []
      outputs:
        - projects/minimal_grid_project/outputs/reports/minimal_grid_report.json
```

### Stage Fields

| Field | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Stable stage identifier used in logs and run manifests. |
| `command` | yes | Shell command executed from repository root when `pathBase: repo`. |
| `needs` | optional | Stage IDs that should run before this stage. |
| `inputs` | optional | Files consumed by the stage. |
| `outputs` | optional | Files produced by the stage. |

## Path Rules

Prefer `spec.pathBase: repo` for published workflows. It makes paths stable and
readable:

```yaml
projects/minimal_grid_project/outputs/reports/minimal_grid_report.json
instances/default/digital_twin/base/buildings.parquet
configs/geography/tr01.json
```

Avoid nested relative paths such as `../../instances/default/digital_twin/...` in published
project manifests.

## Report Validation

Required reports are parsed with `gridalyn.foundation.validate_report`.
They must include:

- `report_id`;
- `schema_version`;
- `created_at`;
- `source_domain`;
- `inputs`;
- `artifacts`;
- `summary`;
- `validation`.

Use [Reports](../platform/reports.md) for the full report contract.

## Commands

```bash
uv run gridalyn project validate projects/minimal_grid_project --check-artifacts
uv run gridalyn project plan projects/minimal_grid_project
uv run gridalyn project run projects/minimal_grid_project
uv run gridalyn project status projects/minimal_grid_project --check-artifacts
```
