"""Foundation contracts for governance, validation, and artifacts.

This facade is the stable home for cross-cutting platform contracts.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

_LAZY_EXPORTS = {
    "ProjectDir": ("gridalyn.foundation.platform", "ProjectDir"),
    "WorkspaceRoot": ("gridalyn.foundation.platform", "WorkspaceRoot"),
    "ArtifactPolicy": ("gridalyn.foundation.platform", "ArtifactPolicy"),
    "ArtifactPolicyReport": ("gridalyn.foundation.platform", "ArtifactPolicyReport"),
    "ArtifactLayout": ("gridalyn.foundation.platform", "ArtifactLayout"),
    "GridalynWorkspace": ("gridalyn.foundation.platform", "GridalynWorkspace"),
    "ModelVersion": ("gridalyn.foundation.platform", "ModelVersion"),
    "ReportMetadata": ("gridalyn.foundation.platform", "ReportMetadata"),
    "StudyRun": ("gridalyn.foundation.platform", "StudyRun"),
    "build_model_version": ("gridalyn.foundation.platform", "build_model_version"),
    "build_report": ("gridalyn.foundation.platform", "build_report"),
    "build_study_run": ("gridalyn.foundation.platform", "build_study_run"),
    "check_artifact_policy": ("gridalyn.foundation.platform", "check_artifact_policy"),
    "file_reference": ("gridalyn.foundation.platform", "file_reference"),
    "find_workspace_root": ("gridalyn.foundation.platform", "find_workspace_root"),
    "layout_from_environment": (
        "gridalyn.foundation.platform",
        "layout_from_environment",
    ),
    "read_json_report": ("gridalyn.foundation.platform", "read_json_report"),
    "validate_report": ("gridalyn.foundation.platform", "validate_report"),
    "validate_workspace": ("gridalyn.foundation.platform", "validate_workspace"),
    "workspace_from_path": ("gridalyn.foundation.platform", "workspace_from_path"),
    "workspace_from_root": ("gridalyn.foundation.platform", "workspace_from_root"),
    "workspace_from_environment": (
        "gridalyn.foundation.platform",
        "workspace_from_environment",
    ),
    "write_manifest": ("gridalyn.foundation.platform", "write_manifest"),
    "write_report": ("gridalyn.foundation.platform", "write_report"),
}


if TYPE_CHECKING:
    # Static re-exports: mypy checks callers against the real signatures while
    # run time stays lazy (bd 6ns.1). pyflakes cannot see that __all__ lists
    # them, hence the noqa.
    from gridalyn.foundation.platform.roots import (  # noqa: F401
        ProjectDir as ProjectDir,
    )
    from gridalyn.foundation.platform.roots import (  # noqa: F401
        WorkspaceRoot as WorkspaceRoot,
    )
    from gridalyn.foundation.platform.workspace import (  # noqa: F401
        ArtifactLayout as ArtifactLayout,
    )
    from gridalyn.foundation.platform.workspace import (  # noqa: F401
        GridalynWorkspace as GridalynWorkspace,
    )
    from gridalyn.foundation.platform.workspace import (  # noqa: F401
        find_workspace_root as find_workspace_root,
    )
    from gridalyn.foundation.platform.workspace import (  # noqa: F401
        layout_from_environment as layout_from_environment,
    )
    from gridalyn.foundation.platform.workspace import (  # noqa: F401
        workspace_from_environment as workspace_from_environment,
    )
    from gridalyn.foundation.platform.workspace import (  # noqa: F401
        workspace_from_path as workspace_from_path,
    )
    from gridalyn.foundation.platform.workspace import (  # noqa: F401
        workspace_from_root as workspace_from_root,
    )

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str):
    if name in _LAZY_EXPORTS:
        module_name, attr_name = _LAZY_EXPORTS[name]
        value = getattr(import_module(module_name), attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'gridalyn.foundation' has no attribute {name!r}")


def __dir__() -> list[str]:
    """List the module namespace plus every lazily exported public name.

    Returns:
        Sorted names, so ``dir()`` and :func:`inspect.getmembers` see the
        lazy exports that ``__getattr__`` resolves on demand.
    """
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
