"""Unified workspace validation facade."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any

from gridalyn.foundation.platform.artifacts import check_artifact_policy
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

    workspace = GridalynWorkspace.discover(root)
    repo_root = workspace.root
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
        # LAYER-DIRECTION EXCEPTION: foundation -> gridalyn.projects.api.
        # This facade composes a repo-level check (artifact policy) with a
        # per-project contract check, so it spans both layers by construction.
        # It lives in `foundation` because that is where its published entry
        # point is: `gridalyn.foundation.validate_workspace`
        # (docs/sdk/public-contract.md) exported via two `_LAZY_EXPORTS` maps
        # and imported directly by `gridalyn.interfaces.cli.gridalyn`.
        # The import is kept inside this loop on purpose: importing this
        # module, or validating a workspace with no projects, pulls no
        # `gridalyn.projects` module into `sys.modules`.
        # Inverting it (injecting the validator, or moving this loop up into
        # the `projects` layer) is the right fix but is not a local edit --
        # it must relocate the published symbol and update
        # `gridalyn/foundation/__init__.py`,
        # `gridalyn/foundation/platform/__init__.py` and
        # `gridalyn/interfaces/cli/gridalyn.py`. Doing that removes this
        # exception; nothing less does.
        # Registered in tests/test_layer_direction.py::_DOCUMENTED_EXCEPTIONS.
        project_api = import_module("gridalyn.projects.api")

        report = project_api.validate_project(
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
            regression = project_api.project_regression(repo_root / project_path)
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
