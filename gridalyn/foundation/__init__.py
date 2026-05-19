"""Foundation contracts for governance, validation, and artifacts.

This facade is the stable home for cross-cutting platform contracts. It
re-exports the current implementation modules without forcing a disruptive
package move.
"""

from __future__ import annotations

from importlib import import_module

_LAZY_EXPORTS = {
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
    "COMPAT_MODULE_ALIASES": ("gridalyn.foundation.platform", "COMPAT_MODULE_ALIASES"),
    "COMPAT_SUBMODULE_ALIASES": ("gridalyn.foundation.platform", "COMPAT_SUBMODULE_ALIASES"),
    "file_reference": ("gridalyn.foundation.platform", "file_reference"),
    "find_workspace_root": ("gridalyn.foundation.platform", "find_workspace_root"),
    "project_sense_check": ("gridalyn.foundation.platform", "project_sense_check"),
    "project_verify": ("gridalyn.foundation.platform", "project_verify"),
    "read_json_report": ("gridalyn.foundation.platform", "read_json_report"),
    "validate_report": ("gridalyn.foundation.platform", "validate_report"),
    "validate_workspace": ("gridalyn.foundation.platform", "validate_workspace"),
    "workspace_from_path": ("gridalyn.foundation.platform", "workspace_from_path"),
    "workspace_from_root": ("gridalyn.foundation.platform", "workspace_from_root"),
    "write_manifest": ("gridalyn.foundation.platform", "write_manifest"),
    "write_report": ("gridalyn.foundation.platform", "write_report"),
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str):
    if name in _LAZY_EXPORTS:
        module_name, attr_name = _LAZY_EXPORTS[name]
        value = getattr(import_module(module_name), attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'gridalyn.foundation' has no attribute {name!r}")
