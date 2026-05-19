"""Unified workspace validation facade."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gridalyn.foundation.platform.artifacts import check_artifact_policy
from gridalyn.foundation.platform.projects import project_regression, validate_project
from gridalyn.foundation.platform.workspace import GridalynWorkspace


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
    """Validate repository-level policy and one or more project contracts."""

    repo_root = Path(root).resolve()
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

    workspace = GridalynWorkspace(repo_root)
    project_paths = (
        list(projects)
        if projects is not None
        else [path.relative_to(repo_root).as_posix() for path in workspace.project_paths()]
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


__all__ = ["validate_workspace"]
