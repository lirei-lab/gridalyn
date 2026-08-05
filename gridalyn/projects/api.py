"""Public project workspace API."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from gridalyn.foundation.platform.reports import read_json_report, validate_report
from gridalyn.projects.loader import load_project as _load_project
from gridalyn.projects.models import StudyProject, ValidationReport, WorkflowStage
from gridalyn.projects.outputs import prepare_project_workspace
from gridalyn.projects.regression import run_project_regression
from gridalyn.projects.runner import default_manifest_path, plan_stages, run_project
from gridalyn.projects.sense_checks import project_sense_check as _project_sense_check
from gridalyn.projects.templates import TEMPLATES
from gridalyn.projects.validation import validate_project_file


@dataclass(frozen=True)
class CreatedProject:
    """Paths to the workspace :func:`init_project` just wrote.

    Returned so a caller can go straight from scaffolding a project to loading
    or running it, without re-deriving the two YAML paths from the root.

    Attributes:
        root: Project workspace directory that was created or populated.
        project_file: Path to the generated ``project.yaml``.
        workflow_file: Path to the generated ``workflow.yaml``.
    """

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
    echo: bool = False,
    stages: list[str] | None = None,
) -> list[str]:
    """Run or dry-run a project workflow.

    ``echo`` streams per-stage progress to stderr. ``stages`` restricts the
    run to the named stages plus their transitive dependencies.
    """
    project = (
        project_or_path
        if isinstance(project_or_path, StudyProject)
        else load_project(project_or_path)
    )
    return run_project(
        project,
        dry_run=dry_run,
        manifest_path=manifest_path,
        echo=echo,
        stages=stages,
    )


def project_regression(path: Path | str) -> dict:
    """Run a project regression baseline when one is configured."""
    project = load_project(path)
    baseline = project.root / "baselines" / "results_baseline.json"
    if not baseline.exists():
        return {
            "project": project.name,
            "valid": False,
            "checked_count": 0,
            "errors": [f"missing regression baseline: {baseline}"],
        }

    report = run_project_regression(project_root=project.root)
    report["returncode"] = 0 if report.get("valid") else 1
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
    valid = bool(
        contract.valid
        and status["valid"]
        and status["reports"]["ready"]
        and sense["valid"]
    )
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
            "report": str(
                project.root / "outputs/reports/project_sense_check_report.json"
            ),
        },
    }


def list_projects(root: Path | str = ".") -> list[dict[str, object]]:
    """List governed project workspaces under a repository or projects folder."""
    root_path = Path(root)
    projects_root = (
        root_path if root_path.name == "projects" else root_path / "projects"
    )
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
        "problem": {
            "type": project.problem.type,
            "dataset": project.problem.dataset,
            "environment": project.problem.environment,
            "objective": project.problem.objective,
            "scenario_count": len(project.problem.scenarios),
            "experiment_count": len(project.experiments),
        },
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
        project.raw.get("spec", {}).get("validation", {}).get("requiredReports", [])
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
    invalid_count = sum(
        1 for record in records if record["exists"] and not record["valid"]
    )
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
    """Create a project workspace from a registered template."""
    root = Path(target)
    project_name = _slug(name or root.name)
    if template not in TEMPLATES:
        available = ", ".join(sorted(TEMPLATES))
        raise ValueError(
            f"unsupported project template: {template} (available: {available})"
        )
    selected = TEMPLATES[template]
    if root.exists() and any(root.iterdir()) and not force:
        raise FileExistsError(f"target project directory is not empty: {root}")

    (root / "inputs").mkdir(parents=True, exist_ok=True)
    prepare_project_workspace(root)
    (root / "scripts").mkdir(parents=True, exist_ok=True)

    project_file = root / "project.yaml"
    workflow_file = root / "workflow.yaml"
    readme_file = root / "README.md"

    if force or not project_file.exists():
        project_file.write_text(selected.project_yaml(project_name), encoding="utf-8")
    if force or not workflow_file.exists():
        workflow_file.write_text(selected.workflow_yaml(project_name), encoding="utf-8")
    if force or not readme_file.exists():
        readme_file.write_text(selected.readme(project_name), encoding="utf-8")
    for relative, builder in selected.scripts.items():
        script_file = root / relative
        if force or not script_file.exists():
            script_file.parent.mkdir(parents=True, exist_ok=True)
            script_file.write_text(builder(project_name), encoding="utf-8")

    return CreatedProject(
        root=root,
        project_file=project_file,
        workflow_file=workflow_file,
    )
