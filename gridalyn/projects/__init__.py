"""Project and workflow contracts for reproducible Gridalyn studies."""

from __future__ import annotations

from importlib import import_module

from gridalyn.projects.loader import load_workflow
from gridalyn.projects.models import (
    StudyProject,
    ValidationReport,
    WorkflowSpec,
    WorkflowStage,
)
from gridalyn.projects.validation import validate_project_file

_LAZY_EXPORTS = {
    "CreatedProject": ("gridalyn.foundation.platform.projects", "CreatedProject"),
    "init_project": ("gridalyn.foundation.platform.projects", "init_project"),
    "list_projects": ("gridalyn.foundation.platform.projects", "list_projects"),
    "load_project": ("gridalyn.foundation.platform.projects", "load_project"),
    "plan_project": ("gridalyn.foundation.platform.projects", "plan_project"),
    "project_regression": ("gridalyn.foundation.platform.projects", "project_regression"),
    "project_sense_check": ("gridalyn.foundation.platform.projects", "project_sense_check"),
    "project_status": ("gridalyn.foundation.platform.projects", "project_status"),
    "project_verify": ("gridalyn.foundation.platform.projects", "project_verify"),
    "project_verify_all": ("gridalyn.foundation.platform.projects", "project_verify_all"),
    "run_workflow": ("gridalyn.foundation.platform.projects", "run_workflow"),
    "validate_project": ("gridalyn.foundation.platform.projects", "validate_project"),
}

__all__ = [
    "CreatedProject",
    "StudyProject",
    "ValidationReport",
    "WorkflowSpec",
    "WorkflowStage",
    "init_project",
    "list_projects",
    "load_project",
    "load_workflow",
    "plan_project",
    "project_regression",
    "project_sense_check",
    "project_status",
    "project_verify",
    "project_verify_all",
    "run_workflow",
    "validate_project",
    "validate_project_file",
]


def __getattr__(name: str):
    if name in _LAZY_EXPORTS:
        module_name, attr_name = _LAZY_EXPORTS[name]
        value = getattr(import_module(module_name), attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'gridalyn.projects' has no attribute {name!r}")
