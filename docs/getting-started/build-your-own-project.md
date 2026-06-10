# Build Your Own Project

This page walks from an empty directory to a governed, verifiable, and
regression-protected Gridalyn project. It assumes you already ran the
[Quickstart](quickstart.md).

## 1. Scaffold From A Template

List the available templates and create a workspace:

```bash
uv run gridalyn project init --list-templates
uv run gridalyn project init projects/my_study --name="My Study" --template=powerflow-demo
```

Templates:

| Template | What you get |
| --- | --- |
| `minimal` | Smallest valid contract with a placeholder workflow. |
| `grid-study` | Contract plus a summary-report stage wired for verification. |
| `powerflow-demo` | Runnable IEEE 33-bus power-flow study with a figure and a governed report. |

## 2. Declare Your Inputs In project.yaml

Model inputs live under `spec.inputs` and are loaded by SDK helpers, so the
contract stays the single source of truth. For example, a radial feeder:

```yaml
spec:
  inputs:
    sourceNetwork:
      model:
        type: radial_feeder
        name: my_feeder
        busCount: 5
        snMva: 1.0
        baseVoltageKv: 12.66
        slackVmPu: 1.0
        loadsMw:
          1: 0.4
          2: 0.3
          3: 0.4
          4: 0.2
```

Power-flow scenarios belong in `spec.problem.scenarios` and can carry
parameters that the scenario loader understands:

```yaml
spec:
  problem:
    scenarios:
      - id: load_growth_20
        role: demand_growth_case
        description: Uniform 20 percent demand growth.
        parameters:
          loadMultiplier: 1.2
```

If a required field is missing, validation errors now point at the exact YAML
path and list what is present, so fixing the contract does not require reading
the source code.

## 3. Write Stage Scripts With project_script

Every workflow stage script starts the same way:

```python
from gridalyn.projects.scripting import project_script

script = project_script()
```

`project_script()` finds the surrounding `project.yaml`, loads the project,
creates the standard `outputs/*` directories, and configures headless
matplotlib. From there:

```python
feeder = script.load_radial_feeder_spec()          # from spec.inputs.sourceNetwork
der_assets = script.load_der_dispatch_assets()     # from spec.inputs.derAssets
figure = script.figures_dir / "voltage_profile.png"

script.write_report(
    "my_study_report",                              # outputs/reports/my_study_report.json
    artifacts=[script.file_reference(figure)],
    summary={"min_voltage_pu": 0.95},
)
```

Reports written through `script.write_report` follow the platform report
contract and are stamped with the project name automatically.

## 4. Wire Stages In workflow.yaml

```yaml
spec:
  stages:
    - id: prepare_workspace
      command: python -m gridalyn.interfaces.cli.project prepare-workspace .
    - id: run_study
      needs:
        - prepare_workspace
      command: python scripts/run_study.py
      outputs:
        - outputs/reports/my_study_report.json
```

Run the full workflow, or just one stage and its dependencies while iterating:

```bash
uv run gridalyn project run projects/my_study
uv run gridalyn project run projects/my_study --stage run_study
```

## 5. Verify

```bash
uv run gridalyn project validate projects/my_study
uv run gridalyn project verify projects/my_study
```

`verify` combines contract validation, artifact status, and the declarative
`senseChecks` from `project.yaml` into one pass/fail payload.

## 6. Pin A Regression Baseline

Once results are stable, pin the key metrics so future changes cannot silently
alter them. Create `baselines/results_baseline.json`:

```json
{
  "metric_tolerance": {"absolute": 1e-06},
  "metrics": [
    {
      "id": "summary.min_voltage_pu",
      "source": "outputs/reports/my_study_report.json",
      "json_path": ["summary", "min_voltage_pu"],
      "expected": 0.9503,
      "tolerance": 1e-06
    }
  ]
}
```

Then run:

```bash
uv run gridalyn project regression projects/my_study
```

All bundled demo projects carry such a baseline; use any of them under
`projects/*/baselines/` as a reference.

## Read Next

- [Project Model](../projects/project-model.md) — the full contract reference.
- [Run Demo Projects](run-demo-projects.md) — the bundled examples to copy from.
- [Naming Conventions](../concepts/naming-conventions.md) — how `load_*`,
  `build_*`, and `write_*` helpers divide the work.
