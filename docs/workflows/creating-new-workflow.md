# Creating a New Workflow

Use this guide when adding a new reproducible study. The goal is to create a
project that can be run by CLI, imported from Python, validated in CI, and later
connected to the dashboard or another downstream application.

## 1. Create the Project

```bash
uv run gridalyn project init projects/my_case --name my_case
```

This creates:

```text
projects/my_case/
  project.yaml
  workflow.yaml
  README.md
  inputs/
  outputs/
```

## 2. Declare Inputs

Put input references in `project.yaml`. Prefer repository-root paths with
`spec.pathBase: repo`.

```yaml
spec:
  pathBase: repo
  inputs:
    geography:
      source: configs/geography/tr01.json
    grid:
      powergridConfig: configs/grid/powergrid_config.json
```

If an input is large or external, document how to obtain it instead of hiding
that logic in a plotting script.

## 3. Write Stage Scripts

Put project-specific orchestration scripts under:

```text
projects/my_case/scripts/
```

Reusable functions belong in `gridalyn/`.

Generated artifacts should go under:

```text
projects/my_case/outputs/data/
projects/my_case/outputs/json/
projects/my_case/outputs/figures/
projects/my_case/outputs/reports/
projects/my_case/outputs/manifests/
```

For studies with stable expected numerical outputs, add a small regression
baseline under:

```text
projects/my_case/baselines/
```

and expose a project-local verifier at:

```text
projects/my_case/scripts/verify_regression.py
```

Then the common CLI can run:

```bash
uv run gridalyn project regression projects/my_case
```

## 4. Declare the Workflow

Each stage should list the command, important inputs, and important outputs.

```yaml
spec:
  stages:
    - id: build_inputs
      command: uv run python projects/my_case/scripts/build_inputs.py
      outputs:
        - projects/my_case/outputs/json/input_summary.json

    - id: run_simulation
      needs: [build_inputs]
      command: uv run python projects/my_case/scripts/run_simulation.py
      inputs:
        - projects/my_case/outputs/json/input_summary.json
      outputs:
        - projects/my_case/outputs/data/simulation_results.parquet
```

## 5. Add Reports

Reports should use the public contract in `gridalyn.foundation`.

```python
from gridalyn.foundation import ReportMetadata, file_reference, write_report

write_report(
    "projects/my_case/outputs/reports/sample_report.json",
    metadata=ReportMetadata(report_id="sample_report", source_domain="my_case"),
    inputs=[file_reference("projects/my_case/outputs/data/simulation_results.parquet")],
    summary={"ready": True},
    validation={"valid": True, "errors": [], "warnings": []},
)
```

Then declare required reports in `project.yaml`:

```yaml
spec:
  validation:
    requiredReports:
      - projects/my_case/outputs/reports/sample_report.json
```

## 6. Verify

```bash
uv run gridalyn project validate projects/my_case --check-artifacts
uv run gridalyn project plan projects/my_case
uv run gridalyn project run projects/my_case
uv run gridalyn project status projects/my_case --check-artifacts
```

## 7. Connect to Dashboard Or Downstream Apps

Use `instances/default/digital_twin/dashboard/catalog.json` or project reports
for dashboard summary cards. Avoid making the dashboard depend on
project-specific plotting scripts or publication material.
