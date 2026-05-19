"""Public Gridalyn platform API.

This module is the stable Python entry point for applications that want to
embed the platform without shelling out to compatibility scripts. Exports are
loaded lazily so lightweight commands such as ``gridalyn validate`` do not pull
in simulation or plotting dependencies.
"""

from __future__ import annotations

from importlib import import_module


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
    "AggregatorPortfolio": ("gridalyn.foundation.platform.flexibility", "AggregatorPortfolio"),
    "DispatchInstruction": ("gridalyn.foundation.platform.flexibility", "DispatchInstruction"),
    "FlexibilityOperationContext": ("gridalyn.foundation.platform.flexibility", "FlexibilityOperationContext"),
    "FlexibilityOperationValidation": ("gridalyn.foundation.platform.flexibility", "FlexibilityOperationValidation"),
    "FlexibilityOffer": ("gridalyn.foundation.platform.flexibility", "FlexibilityOffer"),
    "NetworkConstraint": ("gridalyn.foundation.platform.flexibility", "NetworkConstraint"),
    "SettlementRecord": ("gridalyn.foundation.platform.flexibility", "SettlementRecord"),
    "build_aggregator_portfolios": ("gridalyn.foundation.platform.flexibility", "build_aggregator_portfolios"),
    "build_dispatch_instructions": ("gridalyn.foundation.platform.flexibility", "build_dispatch_instructions"),
    "build_network_constraint_set": ("gridalyn.foundation.platform.flexibility", "build_network_constraint_set"),
    "build_operation_context": ("gridalyn.foundation.platform.flexibility", "build_operation_context"),
    "build_operational_kpi_report": ("gridalyn.foundation.platform.flexibility", "build_operational_kpi_report"),
    "build_provider_offers": ("gridalyn.foundation.platform.flexibility", "build_provider_offers"),
    "build_settlement_records": ("gridalyn.foundation.platform.flexibility", "build_settlement_records"),
    "run_flexibility_clearing_operation": ("gridalyn.foundation.platform.flexibility", "run_flexibility_clearing_operation"),
    "summarize_network_constraints": ("gridalyn.foundation.platform.flexibility", "summarize_network_constraints"),
    "validate_flexibility_operation_inputs": ("gridalyn.foundation.platform.flexibility", "validate_flexibility_operation_inputs"),
    "OperationRun": ("gridalyn.operations", "OperationRun"),
    "OperationRunValidation": ("gridalyn.operations", "OperationRunValidation"),
    "build_operation_run": ("gridalyn.operations", "build_operation_run"),
    "validate_operation_run": ("gridalyn.operations", "validate_operation_run"),
    "write_operation_run": ("gridalyn.operations", "write_operation_run"),
    "COMPAT_MODULE_ALIASES": ("gridalyn.foundation.platform.compatibility", "COMPAT_MODULE_ALIASES"),
    "COMPAT_SUBMODULE_ALIASES": (
        "gridalyn.foundation.platform.compatibility",
        "COMPAT_SUBMODULE_ALIASES",
    ),
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str):
    if name in _LAZY_EXPORTS:
        module_name, attr_name = _LAZY_EXPORTS[name]
        value = getattr(import_module(module_name), attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'gridalyn.foundation.platform' has no attribute {name!r}")
