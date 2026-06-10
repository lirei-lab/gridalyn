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
    "load_der_dispatch_assets": ("gridalyn.projects.model_inputs", "load_der_dispatch_assets"),
    "load_numeric_profile_array": ("gridalyn.projects.model_inputs", "load_numeric_profile_array"),
    "load_prosumer_assets": ("gridalyn.projects.model_inputs", "load_prosumer_assets"),
    "load_radial_feeder_spec": ("gridalyn.projects.model_inputs", "load_radial_feeder_spec"),
    "load_voltage_control_der_spec": (
        "gridalyn.projects.model_inputs",
        "load_voltage_control_der_spec",
    ),
    "plan_project": ("gridalyn.projects.api", "plan_project"),
    "prepare_project_workspace": ("gridalyn.projects.api", "prepare_project_workspace"),
    "ProjectScript": ("gridalyn.projects.scripting", "ProjectScript"),
    "project_script": ("gridalyn.projects.scripting", "project_script"),
    "project_regression": ("gridalyn.projects.api", "project_regression"),
    "project_input": ("gridalyn.projects.model_inputs", "project_input"),
    "run_project_regression": ("gridalyn.projects.regression", "run_project_regression"),
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
    "ProjectScript",
    "ScenarioSpec",
    "StudyProject",
    "ValidationReport",
    "WorkflowSpec",
    "WorkflowStage",
    "init_project",
    "list_projects",
    "load_project",
    "load_der_dispatch_assets",
    "load_numeric_profile_array",
    "load_prosumer_assets",
    "load_radial_feeder_spec",
    "load_voltage_control_der_spec",
    "load_workflow",
    "plan_project",
    "prepare_project_workspace",
    "project_regression",
    "project_input",
    "project_sense_check",
    "project_status",
    "project_verify",
    "project_verify_all",
    "run_project_regression",
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
