"""Public Gridalyn foundation platform API.

This module is the stable Python entry point for applications that want to
embed foundation contracts. Exports are loaded lazily so lightweight commands
such as ``gridalyn validate`` do not pull in simulation or plotting
dependencies.
"""

from __future__ import annotations

from importlib import import_module


_LAZY_EXPORTS = {
    "ArtifactPolicy": ("gridalyn.foundation.platform.artifacts", "ArtifactPolicy"),
    "ArtifactPolicyReport": ("gridalyn.foundation.platform.artifacts", "ArtifactPolicyReport"),
    "check_artifact_policy": ("gridalyn.foundation.platform.artifacts", "check_artifact_policy"),
    "validate_workspace": ("gridalyn.foundation.platform.validation", "validate_workspace"),
    "ArtifactLayout": ("gridalyn.foundation.platform.workspace", "ArtifactLayout"),
    "GridalynWorkspace": ("gridalyn.foundation.platform.workspace", "GridalynWorkspace"),
    "find_workspace_root": ("gridalyn.foundation.platform.workspace", "find_workspace_root"),
    "workspace_from_path": ("gridalyn.foundation.platform.workspace", "workspace_from_path"),
    "workspace_from_root": ("gridalyn.foundation.platform.workspace", "workspace_from_root"),
    "ReportMetadata": ("gridalyn.foundation.platform.reports", "ReportMetadata"),
    "build_report": ("gridalyn.foundation.platform.reports", "build_report"),
    "file_reference": ("gridalyn.foundation.platform.reports", "file_reference"),
    "read_json_report": ("gridalyn.foundation.platform.reports", "read_json_report"),
    "validate_report": ("gridalyn.foundation.platform.reports", "validate_report"),
    "write_manifest": ("gridalyn.foundation.platform.reports", "write_manifest"),
    "write_report": ("gridalyn.foundation.platform.reports", "write_report"),
    "ModelVersion": ("gridalyn.foundation.platform.governance", "ModelVersion"),
    "StudyRun": ("gridalyn.foundation.platform.governance", "StudyRun"),
    "build_model_version": ("gridalyn.foundation.platform.governance", "build_model_version"),
    "build_study_run": ("gridalyn.foundation.platform.governance", "build_study_run"),
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str):
    if name in _LAZY_EXPORTS:
        module_name, attr_name = _LAZY_EXPORTS[name]
        value = getattr(import_module(module_name), attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'gridalyn.foundation.platform' has no attribute {name!r}")
