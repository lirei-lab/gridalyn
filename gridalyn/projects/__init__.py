"""Project and workflow contracts for reproducible Gridalyn studies."""

from __future__ import annotations

from importlib import import_module

from gridalyn.projects.loader import load_workflow
from gridalyn.projects.models import (
    ExperimentSpec,
    ProblemSpec,
    ScenarioSpec,
    StudyProject,
    ValidationReport,
    WorkflowSpec,
    WorkflowStage,
)
from gridalyn.projects.validation import validate_project_file

_LAZY_EXPORTS = {
    "CreatedProject": ("gridalyn.projects.api", "CreatedProject"),
    "init_project": ("gridalyn.projects.api", "init_project"),
    "list_projects": ("gridalyn.projects.api", "list_projects"),
    "load_project": ("gridalyn.projects.api", "load_project"),
    "plan_project": ("gridalyn.projects.api", "plan_project"),
    "prepare_project_workspace": ("gridalyn.projects.api", "prepare_project_workspace"),
    "project_regression": ("gridalyn.projects.api", "project_regression"),
    "project_sense_check": ("gridalyn.projects.api", "project_sense_check"),
    "project_status": ("gridalyn.projects.api", "project_status"),
    "project_verify": ("gridalyn.projects.api", "project_verify"),
    "project_verify_all": ("gridalyn.projects.api", "project_verify_all"),
    "run_workflow": ("gridalyn.projects.api", "run_workflow"),
    "validate_project": ("gridalyn.projects.api", "validate_project"),
}

__all__ = [
    "CreatedProject",
    "ExperimentSpec",
    "ProblemSpec",
    "ScenarioSpec",
    "StudyProject",
    "ValidationReport",
    "WorkflowSpec",
    "WorkflowStage",
    "init_project",
    "list_projects",
    "load_project",
    "load_workflow",
    "plan_project",
    "prepare_project_workspace",
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
