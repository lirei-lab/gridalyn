"""Delegating socket for the composed workspace validator.

``validate_workspace`` composes a repo-level check (artifact policy) with
per-project contract checks, so its implementation spans layers above
``foundation``. The composed implementation therefore lives in the projects
layer, which registers it here at import time through
:func:`register_workspace_validator`. This module keeps only the published
entry point -- ``gridalyn.foundation.validate_workspace``, exported via two
``_LAZY_EXPORTS`` maps -- and holds no upward dependency of its own, so the
layer direction stays strictly downward with no documented exception.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class WorkspaceValidator(Protocol):
    """Callable contract for a composed workspace validator."""

    def __call__(
        self,
        root: Path | str = ".",
        *,
        projects: list[str] | tuple[str, ...] | None = None,
        check_project_artifacts: bool = True,
        run_regression: bool = False,
    ) -> dict[str, Any]:
        """Validate the workspace at ``root`` and return the check payload."""
        ...


_workspace_validator: WorkspaceValidator | None = None


def register_workspace_validator(validator: WorkspaceValidator) -> None:
    """Register the composed workspace validator implementation.

    Called by the projects layer's ``validation`` module when it is imported.
    Re-registration overwrites the previous validator, so repeated imports
    stay idempotent.

    Args:
        validator: Implementation composing the repo-level artifact-policy
            check with the per-project contract checks.
    """
    global _workspace_validator
    _workspace_validator = validator


def validate_workspace(
    root: Path | str = ".",
    *,
    projects: list[str] | tuple[str, ...] | None = None,
    check_project_artifacts: bool = True,
    run_regression: bool = False,
) -> dict[str, Any]:
    """Validate repository-level policy and one or more project contracts.

    Delegates to the validator the projects layer registers on import; every
    supported entry point (the ``gridalyn`` CLI, ``from gridalyn import
    projects``, the project scripting helpers) imports that layer before
    calling this function.

    Args:
        root: Workspace root, or any path inside it, to validate.
        projects: Repo-relative project paths to check; when ``None``, every
            project the workspace discovers is checked.
        check_project_artifacts: Also check required project reports and
            figures exist.
        run_regression: Also run configured project regression checks.

    Returns:
        The composed check payload: ``{"valid", "checks", "summary"}``.

    Raises:
        RuntimeError: If no validator has been registered yet, with the
            remediation in the message.
    """
    if _workspace_validator is None:
        raise RuntimeError(
            "gridalyn.foundation.platform.validation.validate_workspace: no "
            "workspace validator is registered; the projects layer registers "
            "one when it is imported -- run 'from gridalyn import projects' "
            "before calling validate_workspace"
        )
    return _workspace_validator(
        root,
        projects=projects,
        check_project_artifacts=check_project_artifacts,
        run_regression=run_regression,
    )


__all__ = ["WorkspaceValidator", "register_workspace_validator", "validate_workspace"]
