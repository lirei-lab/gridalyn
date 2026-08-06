from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from gridalyn.foundation.platform.artifacts import check_artifact_policy
from gridalyn.foundation.platform.validation import register_workspace_validator
from gridalyn.foundation.platform.workspace import GridalynWorkspace
from gridalyn.projects.loader import project_base_dir, read_yaml
from gridalyn.projects.models import ValidationReport

SCHEMA_DIR = Path(__file__).parent / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


def _friendly_hint(error) -> str:
    """Return a remediation hint for common schema validation failures."""
    if error.validator == "required":
        missing = error.message.split("'")[1] if "'" in error.message else "the field"
        return (
            f" — add '{missing}:' at this location; "
            "run 'gridalyn project init' to generate a working template"
        )
    if error.validator == "type":
        expected = error.validator_value
        if isinstance(expected, list):
            expected = " or ".join(str(item) for item in expected)
        return f" — change the value to a YAML {expected}"
    if error.validator == "enum":
        allowed = ", ".join(str(item) for item in error.validator_value)
        return f" — allowed values: {allowed}"
    if error.validator == "additionalProperties":
        return " — remove the unrecognized field or check its spelling"
    return ""


def _validate_schema(
    data: dict,
    schema_name: str,
    report: ValidationReport,
    label: str,
) -> None:
    schema = _load_schema(schema_name)
    validator = Draft202012Validator(schema)
    for error in sorted(validator.iter_errors(data), key=lambda item: list(item.path)):
        path = ".".join(str(part) for part in error.path) or "<root>"
        report.add_error(f"{label}:{path}: {error.message}{_friendly_hint(error)}")


def validate_project_file(  # noqa: C901
    path: Path | str,
    check_artifacts: bool = False,
) -> ValidationReport:
    project_path = Path(path).resolve()
    report = ValidationReport(checked_files=[str(project_path)])
    try:
        project_data = read_yaml(project_path)
    except Exception as exc:
        report.add_error(f"{project_path}: {exc}")
        return report

    _validate_schema(project_data, "study_project.schema.json", report, "project")
    if not report.valid:
        return report
    _validate_problem_contract(project_data, report)
    if not report.valid:
        return report

    try:
        base_dir, _ = project_base_dir(project_path, project_data)
    except Exception as exc:
        report.add_error(f"{project_path}: {exc}")
        return report

    workflow_path = (base_dir / project_data["spec"]["workflow"]["file"]).resolve()
    report.checked_files.append(str(workflow_path))
    if not workflow_path.exists():
        report.add_error(f"workflow file does not exist: {workflow_path}")
        return report

    workflow_data = read_yaml(workflow_path)
    _validate_schema(workflow_data, "workflow.schema.json", report, "workflow")
    if not report.valid:
        return report

    stages = workflow_data["spec"]["stages"]
    stage_ids = [stage["id"] for stage in stages]
    duplicates = sorted(
        {stage_id for stage_id in stage_ids if stage_ids.count(stage_id) > 1}
    )
    for duplicate in duplicates:
        report.add_error(f"duplicate workflow stage id: {duplicate}")

    known = set(stage_ids)
    for stage in stages:
        for dependency in stage.get("needs", []):
            if dependency not in known:
                report.add_error(
                    f"stage {stage['id']} depends on unknown stage {dependency}"
                )

    if check_artifacts:
        validation = project_data["spec"].get("validation", {})
        for key, label in (
            ("requiredReports", "report"),
            ("requiredFigures", "figure"),
        ):
            for relative in validation.get(key, []):
                artifact = (base_dir / relative).resolve()
                report.checked_files.append(str(artifact))
                if not artifact.exists():
                    report.add_error(f"missing required {label}: {artifact}")
                elif artifact.is_file() and artifact.stat().st_size == 0:
                    report.add_error(f"empty required {label}: {artifact}")

    return report


def _validate_problem_contract(project_data: dict, report: ValidationReport) -> None:
    spec = project_data["spec"]
    scenarios = spec["problem"]["scenarios"]
    scenario_ids = [item["id"] for item in scenarios]
    duplicate_scenarios = sorted(
        {
            scenario_id
            for scenario_id in scenario_ids
            if scenario_ids.count(scenario_id) > 1
        }
    )
    for scenario_id in duplicate_scenarios:
        report.add_error(f"duplicate problem scenario id: {scenario_id}")

    known_scenarios = set(scenario_ids)
    experiment_ids = [item["id"] for item in spec.get("experiments", [])]
    duplicate_experiments = sorted(
        {
            experiment_id
            for experiment_id in experiment_ids
            if experiment_ids.count(experiment_id) > 1
        }
    )
    for experiment_id in duplicate_experiments:
        report.add_error(f"duplicate experiment id: {experiment_id}")

    for experiment in spec.get("experiments", []):
        refs: list[str] = []
        if experiment.get("scenario"):
            refs.append(experiment["scenario"])
        refs.extend(experiment.get("scenarios", []))
        for scenario_id in refs:
            if scenario_id not in known_scenarios:
                report.add_error(
                    f"experiment {experiment['id']} references unknown scenario {scenario_id}"
                )


def _check_record(
    *,
    check_id: str,
    valid: bool,
    summary: dict[str, Any] | None = None,
    errors: list[str] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "valid": valid,
        "errors": errors or [],
        "warnings": warnings or [],
        "summary": summary or {},
    }


def validate_workspace(
    root: Path | str = ".",
    *,
    projects: list[str] | tuple[str, ...] | None = None,
    check_project_artifacts: bool = True,
    run_regression: bool = False,
) -> dict[str, Any]:
    """Validate repository-level policy and one or more project contracts.

    This is the composed implementation behind
    ``gridalyn.foundation.validate_workspace``: it is registered into the
    foundation socket (see ``register_workspace_validator``) when this module
    is imported, so the published foundation entry point keeps working while
    the foundation layer itself stays free of upward imports.

    Args:
        root: Workspace root, or any path inside it, to validate.
        projects: Repo-relative project paths to check; when ``None``, every
            project the workspace discovers is checked.
        check_project_artifacts: Also check required project reports and
            figures exist.
        run_regression: Also run configured project regression checks.

    Returns:
        The composed check payload: ``{"valid", "checks", "summary"}``.
    """
    # Imported at call time: gridalyn.projects.api imports this module for
    # validate_project_file, so a module-scope import would be circular.
    from gridalyn.projects.api import project_regression, validate_project

    workspace = GridalynWorkspace.discover(root)
    # ``GridalynWorkspace.__post_init__`` already coerces ``root`` to a
    # resolved Path; ``Path(...)`` narrows the ``Path | str`` annotation.
    repo_root = Path(workspace.root)
    checks: list[dict[str, Any]] = []

    artifact_report = check_artifact_policy(repo_root)
    checks.append(
        _check_record(
            check_id="artifact_policy",
            valid=artifact_report.valid,
            errors=artifact_report.errors,
            warnings=artifact_report.warnings,
            summary=artifact_report.summary,
        )
    )

    project_paths = (
        list(projects)
        if projects is not None
        else [
            path.relative_to(repo_root).as_posix() for path in workspace.project_paths()
        ]
    )
    for project_path in project_paths:
        report = validate_project(
            repo_root / project_path,
            check_artifacts=check_project_artifacts,
        )
        checks.append(
            _check_record(
                check_id=f"project:{project_path}",
                valid=report.valid,
                errors=report.errors,
                warnings=report.warnings,
                summary={"checked_files": report.checked_files},
            )
        )
        if run_regression:
            regression = project_regression(repo_root / project_path)
            checks.append(
                _check_record(
                    check_id=f"regression:{project_path}",
                    valid=bool(regression.get("valid")),
                    errors=list(regression.get("errors", [])),
                    warnings=[],
                    summary={
                        key: value
                        for key, value in regression.items()
                        if key not in {"errors", "warnings"}
                    },
                )
            )

    valid = all(check["valid"] for check in checks)
    return {
        "valid": valid,
        "checks": checks,
        "summary": {
            "root": str(repo_root),
            "check_count": len(checks),
            "failed_count": sum(1 for check in checks if not check["valid"]),
            "project_count": len(project_paths),
            "run_regression": run_regression,
        },
    }


# Importing gridalyn.projects (or this module directly) wires the composed
# validator into the foundation socket, keeping the published
# gridalyn.foundation.validate_workspace entry point behaviour-identical.
register_workspace_validator(validate_workspace)
