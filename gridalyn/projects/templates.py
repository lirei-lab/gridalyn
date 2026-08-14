"""Project scaffold template registry used by ``init_project``."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class ProjectTemplate:
    """Files generated for one ``gridalyn project init`` template."""

    name: str
    description: str
    project_yaml: Callable[[str], str]
    workflow_yaml: Callable[[str], str]
    readme: Callable[[str], str]
    scripts: dict[str, Callable[[str], str]] = field(default_factory=dict)


def _project_yaml(name: str, template: str = "minimal") -> str:
    required_reports = (
        "[]"
        if template == "minimal"
        else "\n      - outputs/reports/project_summary.json"
    )
    sense_checks = (
        "[]"
        if template == "minimal"
        else """
      - id: project_summary_ready
        report: outputs/reports/project_summary.json
        field: summary.ready
        equals: true"""
    )
    experiment_artifacts = (
        "[]"
        if template == "minimal"
        else """
        - outputs/reports/project_summary.json"""
    )
    return f"""apiVersion: gridalyn.io/v1alpha1
kind: StudyProject
metadata:
  name: {name}
  version: 0.1.0
spec:
  pathBase: project
  simulation:
    # The RNG base this study draws from, recorded in provenance.seeds.
    # Scaffolded rather than left out: a project without it records
    # "base": null in every run manifest, which is the state the shipped
    # studies were repaired out of on 2026-08-14. If your stages grow a
    # second independent stream, replace this with a `seeds:` mapping and
    # read each one through ProjectScript.simulation_seed.
    seed: 7
  problem:
    type: grid_study
    dataset: project_inputs
    environment: project_workflow
    objective: Define a reproducible Gridalyn project contract.
    model:
      type: workflow_model
      name: {name}_workflow
    scenarios:
      - id: baseline
        role: template_baseline
        description: Default template scenario for contract validation.
  experiments:
    - id: baseline_run
      scenario: baseline
      objective: Validate the project contract and declared reports.
      metrics: []
      model: {name}_workflow
      artifacts: {experiment_artifacts}
  inputs:
    raw: inputs
  artifacts:
    project:
      data: outputs/data
      reports: outputs/reports
      figures: outputs/figures
      manifests: outputs/manifests
      operations: outputs/operations
  workflow:
    file: workflow.yaml
  validation:
    requiredReports: {required_reports}
    requiredFigures: []
    senseChecks: {sense_checks}
"""


def _minimal_project_yaml(name: str) -> str:
    return _project_yaml(name, "minimal")


def _grid_study_project_yaml(name: str) -> str:
    return _project_yaml(name, "grid-study")


def _workflow_yaml(name: str, template: str = "minimal") -> str:
    if template == "grid-study":
        return f"""apiVersion: gridalyn.io/v1alpha1
kind: Workflow
metadata:
  name: {name}_workflow
spec:
  stages:
    - id: prepare_workspace
      command: "{{python}} -m gridalyn.interfaces.cli.project prepare-workspace ."
      outputs:
        - outputs/data
        - outputs/figures
        - outputs/manifests
        - outputs/operations
        - outputs/reports
    - id: write_summary_report
      needs:
        - prepare_workspace
      command: "{{python}} scripts/write_summary_report.py"
      outputs:
        - outputs/reports/project_summary.json
"""
    return f"""apiVersion: gridalyn.io/v1alpha1
kind: Workflow
metadata:
  name: {name}_workflow
spec:
  stages:
    - id: prepare_inputs
      command: "{{python}} -m gridalyn.interfaces.cli.project prepare-workspace ."
      outputs:
        - outputs/reports
    - id: validate_outputs
      needs:
        - prepare_inputs
      command: "{{python}} -c \\"print('No project-specific validation configured yet')\\""
"""


def _minimal_workflow_yaml(name: str) -> str:
    return _workflow_yaml(name, "minimal")


def _grid_study_workflow_yaml(name: str) -> str:
    return _workflow_yaml(name, "grid-study")


def _readme(name: str, template: str = "minimal") -> str:
    return f"""# {name}

This is a Gridalyn project workspace using the `{template}` template.

## Common Commands

```bash
uv run gridalyn project validate .
uv run gridalyn project plan .
uv run gridalyn project run . --dry-run
uv run gridalyn project status .
```

Place raw inputs under `inputs/` and write generated artifacts under
`outputs/`. Keep reusable implementation in the `gridalyn` package and
project-specific glue under this workspace.

Use `outputs/operations/` for operational instructions, run records, dispatch
tables, and settlement-ready artifacts. Use `outputs/reports/` for stable JSON
reports and `outputs/data/` for derived analytical datasets.

## Report Contract

Project reports should use the platform report contract:

```python
from gridalyn.foundation.platform import ReportMetadata, write_report

write_report(
    "outputs/reports/sample_report.json",
    metadata=ReportMetadata(report_id="sample_report", source_domain="{name}"),
    summary={{"ready": True}},
)
```
"""


def _minimal_readme(name: str) -> str:
    return _readme(name, "minimal")


def _grid_study_readme(name: str) -> str:
    return _readme(name, "grid-study")


def _summary_report_script(name: str) -> str:
    return f'''"""Write the default project summary report for {name}."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    output = Path("outputs/reports/project_summary.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {{
        "report_id": "project_summary",
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_domain": "{name}",
        "project": {{"name": "{name}"}},
        "governance": {{"model_version_id": None, "study_run_id": None}},
        "inputs": [],
        "artifacts": [
            {{"path": "outputs/reports/project_summary.json"}}
        ],
        "summary": {{
            "project": "{name}",
            "template": "grid-study",
            "ready": True
        }},
        "validation": {{"valid": True, "errors": [], "warnings": []}},
    }}
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _powerflow_demo_project_yaml(name: str) -> str:
    return f"""apiVersion: gridalyn.io/v1alpha1
kind: StudyProject
metadata:
  name: {name}
  version: 0.1.0
spec:
  pathBase: project
  simulation:
    # The RNG base this study draws from, recorded in provenance.seeds.
    # Scaffolded rather than left out: a project without it records
    # "base": null in every run manifest, which is the state the shipped
    # studies were repaired out of on 2026-08-14. If your stages grow a
    # second independent stream, replace this with a `seeds:` mapping and
    # read each one through ProjectScript.simulation_seed.
    seed: 7
  problem:
    type: grid_study
    dataset: ieee_33_bus_benchmark
    environment: project_workflow
    objective: Run a benchmark IEEE 33-bus power flow and publish a governed report.
    model:
      type: simulation_model
      name: {name}_powerflow
    scenarios:
      - id: baseline
        role: powerflow_baseline
        description: Deterministic IEEE 33-bus benchmark power flow.
  experiments:
    - id: baseline_run
      scenario: baseline
      objective: Produce the baseline power-flow report and voltage-profile figure.
      metrics:
        - min_voltage_pu
        - max_voltage_pu
      model: {name}_powerflow
      artifacts:
        - outputs/reports/powerflow_demo_report.json
        - outputs/figures/powerflow_demo_voltage_profile.png
  inputs:
    raw: inputs
  artifacts:
    project:
      data: outputs/data
      reports: outputs/reports
      figures: outputs/figures
      manifests: outputs/manifests
      operations: outputs/operations
  workflow:
    file: workflow.yaml
  validation:
    requiredReports:
      - outputs/reports/powerflow_demo_report.json
    requiredFigures:
      - outputs/figures/powerflow_demo_voltage_profile.png
    senseChecks:
      - id: powerflow_converged
        report: outputs/reports/powerflow_demo_report.json
        field: summary.converged
        equals: true
      - id: voltage_above_collapse
        report: outputs/reports/powerflow_demo_report.json
        field: summary.min_voltage_pu
        min: 0.80
"""


def _powerflow_demo_workflow_yaml(name: str) -> str:
    return f"""apiVersion: gridalyn.io/v1alpha1
kind: Workflow
metadata:
  name: {name}_workflow
spec:
  stages:
    - id: prepare_workspace
      command: "{{python}} -m gridalyn.interfaces.cli.project prepare-workspace ."
      outputs:
        - outputs/data
        - outputs/figures
        - outputs/manifests
        - outputs/operations
        - outputs/reports
    - id: run_powerflow_study
      needs:
        - prepare_workspace
      command: "{{python}} scripts/run_powerflow_study.py"
      outputs:
        - outputs/reports/powerflow_demo_report.json
        - outputs/figures/powerflow_demo_voltage_profile.png
"""


def _powerflow_demo_readme(name: str) -> str:
    return f"""# {name}

A runnable Gridalyn power-flow demo on the IEEE 33-bus benchmark feeder,
created from the `powerflow-demo` template.

## Run It

```bash
uv run gridalyn project run .
uv run gridalyn project verify .
```

The run produces a voltage-profile figure under `outputs/figures/` and a
governed JSON report under `outputs/reports/`.

## Make It Yours

Edit `scripts/run_powerflow_study.py` to change the network or the scenario.
The script uses `gridalyn.projects.scripting.project_script`, which resolves
the workspace, prepares `outputs/*`, and writes reports stamped with this
project's name.
"""


def _powerflow_demo_script(name: str) -> str:
    return f'''"""Run the IEEE 33-bus benchmark power flow for {name}."""

from __future__ import annotations

from gridalyn.projects.scripting import project_script
from gridalyn.simulation import (
    build_ieee33_benchmark_feeder,
    write_powerflow_report,
    write_voltage_profile_figure,
)


def main() -> int:
    script = project_script()
    net = build_ieee33_benchmark_feeder(run_powerflow=True)
    figure = write_voltage_profile_figure(
        net,
        script.figures_dir / "powerflow_demo_voltage_profile.png",
        title=f"{{script.name}} - IEEE 33-Bus Voltage Profile",
    )
    write_powerflow_report(
        script.reports_dir / "powerflow_demo_report.json",
        metadata=script.report_metadata("powerflow_demo_report"),
        net=net,
        inputs=[{{"name": "ieee_33_bus", "type": "gridalyn_benchmark_feeder"}}],
        artifacts=[script.file_reference(figure)],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


TEMPLATES: dict[str, ProjectTemplate] = {
    "minimal": ProjectTemplate(
        name="minimal",
        description="Smallest valid project contract with a placeholder workflow.",
        project_yaml=_minimal_project_yaml,
        workflow_yaml=_minimal_workflow_yaml,
        readme=_minimal_readme,
    ),
    "grid-study": ProjectTemplate(
        name="grid-study",
        description="Contract plus a summary-report stage wired for verification.",
        project_yaml=_grid_study_project_yaml,
        workflow_yaml=_grid_study_workflow_yaml,
        readme=_grid_study_readme,
        scripts={"scripts/write_summary_report.py": _summary_report_script},
    ),
    "powerflow-demo": ProjectTemplate(
        name="powerflow-demo",
        description=(
            "Runnable IEEE 33-bus power-flow study producing a figure and a "
            "governed report (requires only base dependencies, e.g. "
            "pandapower)."
        ),
        project_yaml=_powerflow_demo_project_yaml,
        workflow_yaml=_powerflow_demo_workflow_yaml,
        readme=_powerflow_demo_readme,
        scripts={"scripts/run_powerflow_study.py": _powerflow_demo_script},
    ),
}


__all__ = ["ProjectTemplate", "TEMPLATES"]
