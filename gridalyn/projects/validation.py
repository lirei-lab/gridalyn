from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from gridalyn.projects.loader import project_base_dir, read_yaml
from gridalyn.projects.models import ValidationReport


SCHEMA_DIR = Path(__file__).parent / "schemas"


def _load_schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


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
        report.add_error(f"{label}:{path}: {error.message}")


def validate_project_file(
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
    duplicates = sorted({stage_id for stage_id in stage_ids if stage_ids.count(stage_id) > 1})
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
