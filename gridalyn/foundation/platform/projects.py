"""Public project workspace API."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import json
import subprocess
import sys

from gridalyn.projects.loader import load_project as _load_project
from gridalyn.projects.models import StudyProject, ValidationReport, WorkflowStage
from gridalyn.projects.runner import default_manifest_path, plan_stages, run_project
from gridalyn.projects.sense_checks import project_sense_check as _project_sense_check
from gridalyn.projects.validation import validate_project_file
from gridalyn.foundation.platform.reports import read_json_report, validate_report


@dataclass(frozen=True)
class CreatedProject:
    root: Path
    project_file: Path
    workflow_file: Path


def _project_file(path: Path | str) -> Path:
    candidate = Path(path)
    if candidate.name == "project.yaml":
        return candidate
    return candidate / "project.yaml"


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip()).strip("_").lower()
    if not slug:
        raise ValueError("project name must contain at least one letter or number")
    return slug


def load_project(path: Path | str) -> StudyProject:
    """Load a project from either a workspace directory or project.yaml path."""
    return _load_project(_project_file(path))


def validate_project(
    path: Path | str,
    check_artifacts: bool = False,
) -> ValidationReport:
    """Validate a project workspace or project.yaml file."""
    return validate_project_file(_project_file(path), check_artifacts=check_artifacts)


def plan_project(project_or_path: StudyProject | Path | str) -> list[WorkflowStage]:
    """Return workflow stages in execution order."""
    project = (
        project_or_path
        if isinstance(project_or_path, StudyProject)
        else load_project(project_or_path)
    )
    return plan_stages(project)


def run_workflow(
    project_or_path: StudyProject | Path | str,
    dry_run: bool = False,
    manifest_path: Path | str | None = None,
) -> list[str]:
    """Run or dry-run a project workflow."""
    project = (
        project_or_path
        if isinstance(project_or_path, StudyProject)
        else load_project(project_or_path)
    )
    return run_project(project, dry_run=dry_run, manifest_path=manifest_path)


def project_regression(path: Path | str) -> dict:
    """Run a project-local regression verifier when one is configured."""
    project = load_project(path)
    script = project.root / "scripts" / "verify_regression.py"
    if not script.exists():
        return {
            "project": project.name,
            "valid": False,
            "checked_count": 0,
            "errors": [f"missing regression verifier: {script}"],
        }

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--project-root",
            str(project.root),
        ],
        cwd=project.base_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {
            "project": project.name,
            "valid": False,
            "checked_count": 0,
            "errors": ["regression verifier did not emit JSON"],
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }
    report["returncode"] = result.returncode
    if result.stderr:
        report["stderr"] = result.stderr
    return report


def project_sense_check(path: Path | str, write: bool = True) -> dict:
    """Run objective-specific plausibility checks for a project workspace."""
    return _project_sense_check(path, write=write)


def project_verify(path: Path | str, write: bool = True) -> dict:
    """Run the agent-friendly project verification ladder.

    The ladder combines structural validation, artifact/report status, and
    objective-specific sense checks into one JSON payload suitable for humans,
    CI jobs, and coding agents.
    """

    project = load_project(path)
    contract = validate_project(project.path, check_artifacts=True)
    status = project_status(project.path, check_artifacts=True)
    sense = project_sense_check(project.path, write=write)
    valid = bool(contract.valid and status["valid"] and status["reports"]["ready"] and sense["valid"])
    return {
        "project": project.name,
        "valid": valid,
        "contract": {
            "valid": contract.valid,
            "errors": contract.errors,
            "warnings": contract.warnings,
            "checked_files": contract.checked_files,
        },
        "status": status,
        "sense_check": {
            "valid": sense["valid"],
            "score": sense["score"],
            "checked_count": sense["checked_count"],
            "error_count": sense["error_count"],
            "failed_count": sense["failed_count"],
            "errors": sense.get("validation", {}).get("errors", []),
            "warnings": sense.get("validation", {}).get("warnings", []),
            "report": str(project.root / "outputs/reports/project_sense_check_report.json"),
        },
    }


def list_projects(root: Path | str = ".") -> list[dict[str, object]]:
    """List governed project workspaces under a repository or projects folder."""
    root_path = Path(root)
    projects_root = root_path if root_path.name == "projects" else root_path / "projects"
    records: list[dict[str, object]] = []
    if not projects_root.exists():
        return records
    for project_file in sorted(projects_root.glob("*/project.yaml")):
        try:
            project = load_project(project_file)
        except Exception:
            records.append(
                {
                    "name": project_file.parent.name,
                    "path": str(project_file.parent),
                    "valid": False,
                }
            )
            continue
        records.append(
            {
                "name": project.name,
                "version": project.version,
                "path": str(project.root),
                "valid": True,
            }
        )
    return records


def project_verify_all(root: Path | str = ".", write: bool = False) -> dict:
    """Run project verification for every governed project in a workspace."""
    records = []
    for project in list_projects(root):
        path = project["path"]
        try:
            report = project_verify(path, write=write)
        except Exception as exc:
            report = {
                "project": project["name"],
                "valid": False,
                "errors": [str(exc)],
            }
        records.append(report)
    valid = all(record.get("valid") for record in records)
    return {
        "valid": valid,
        "project_count": len(records),
        "passed_count": sum(1 for record in records if record.get("valid")),
        "failed_count": sum(1 for record in records if not record.get("valid")),
        "projects": records,
    }


def project_status(path: Path | str, check_artifacts: bool = False) -> dict:
    """Return a compact status summary for a project workspace."""
    project = load_project(path)
    report = validate_project(project.path, check_artifacts=check_artifacts)
    stages = plan_project(project) if report.valid else []
    manifest_path = default_manifest_path(project)
    report_summary = _project_report_summary(project)
    return {
        "name": project.name,
        "version": project.version,
        "root": str(project.root),
        "project_file": str(project.path),
        "workflow_file": str(project.workflow.path),
        "valid": report.valid,
        "errors": report.errors,
        "warnings": report.warnings,
        "stage_count": len(stages),
        "stages": [stage.id for stage in stages],
        "manifest": str(manifest_path),
        "manifest_exists": manifest_path.exists(),
        "reports": report_summary,
    }


def _project_report_summary(project: StudyProject) -> dict:
    required = (
        project.raw.get("spec", {})
        .get("validation", {})
        .get("requiredReports", [])
    )
    records = []
    for relative in required:
        path = (project.base_dir / relative).resolve()
        errors: list[str] = []
        if path.exists() and path.is_file():
            try:
                errors = validate_report(read_json_report(path))
            except Exception as exc:
                errors = [f"invalid JSON report: {exc}"]
        records.append(
            {
                "path": str(path),
                "relative_path": str(relative),
                "exists": path.exists(),
                "bytes": path.stat().st_size if path.exists() and path.is_file() else 0,
                "valid": path.exists() and not errors,
                "errors": errors,
            }
        )
    found_count = sum(1 for record in records if record["exists"])
    invalid_count = sum(1 for record in records if record["exists"] and not record["valid"])
    return {
        "expected_count": len(records),
        "found_count": found_count,
        "missing_count": len(records) - found_count,
        "invalid_count": invalid_count,
        "ready": found_count == len(records) and invalid_count == 0,
        "items": records,
    }


def init_project(
    target: Path | str,
    name: str | None = None,
    force: bool = False,
    template: str = "minimal",
) -> CreatedProject:
    """Create a minimal project workspace."""
    root = Path(target)
    project_name = _slug(name or root.name)
    if template not in {"minimal", "grid-study"}:
        raise ValueError(f"unsupported project template: {template}")
    if root.exists() and any(root.iterdir()) and not force:
        raise FileExistsError(f"target project directory is not empty: {root}")

    (root / "inputs").mkdir(parents=True, exist_ok=True)
    (root / "outputs" / "data").mkdir(parents=True, exist_ok=True)
    (root / "outputs" / "figures").mkdir(parents=True, exist_ok=True)
    (root / "outputs" / "manifests").mkdir(parents=True, exist_ok=True)
    (root / "outputs" / "operations").mkdir(parents=True, exist_ok=True)
    (root / "outputs" / "reports").mkdir(parents=True, exist_ok=True)
    (root / "scripts").mkdir(parents=True, exist_ok=True)

    project_file = root / "project.yaml"
    workflow_file = root / "workflow.yaml"
    readme_file = root / "README.md"
    report_script = root / "scripts" / "write_summary_report.py"

    if force or not project_file.exists():
        project_file.write_text(_project_yaml(project_name, template), encoding="utf-8")
    if force or not workflow_file.exists():
        workflow_file.write_text(_workflow_yaml(project_name, template), encoding="utf-8")
    if force or not readme_file.exists():
        readme_file.write_text(_readme(project_name, template), encoding="utf-8")
    if template == "grid-study" and (force or not report_script.exists()):
        report_script.write_text(_summary_report_script(project_name), encoding="utf-8")

    return CreatedProject(
        root=root,
        project_file=project_file,
        workflow_file=workflow_file,
    )


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
    return f"""apiVersion: gridalyn.io/v1alpha1
kind: StudyProject
metadata:
  name: {name}
  version: 0.1.0
spec:
  pathBase: project
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


def _workflow_yaml(name: str, template: str = "minimal") -> str:
    if template == "grid-study":
        return f"""apiVersion: gridalyn.io/v1alpha1
kind: Workflow
metadata:
  name: {name}_workflow
spec:
  stages:
    - id: prepare_workspace
      command: python -c "from pathlib import Path; [Path(p).mkdir(parents=True, exist_ok=True) for p in ('outputs/data', 'outputs/figures', 'outputs/manifests', 'outputs/operations', 'outputs/reports')]"
      outputs:
        - outputs/data
        - outputs/figures
        - outputs/manifests
        - outputs/operations
        - outputs/reports
    - id: write_summary_report
      needs:
        - prepare_workspace
      command: python scripts/write_summary_report.py
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
      command: python -c "from pathlib import Path; Path('outputs/reports').mkdir(parents=True, exist_ok=True)"
      outputs:
        - outputs/reports
    - id: validate_outputs
      needs:
        - prepare_inputs
      command: python -c "print('No project-specific validation configured yet')"
"""


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
