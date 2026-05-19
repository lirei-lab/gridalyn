"""Operational services, market clearing, dispatch, and settlement facade."""

from __future__ import annotations

from importlib import import_module

from gridalyn.operations.runs import (
    OperationRun,
    OperationRunValidation,
    build_operation_run,
    validate_operation_run,
    write_operation_run,
)

__all__ = [
    "OperationRun",
    "OperationRunValidation",
    "build_operation_run",
    "validate_operation_run",
    "write_operation_run",
    "SpatialClsResult",
    "allocate_addition_by_headroom",
    "allocate_reduction",
    "apply_locational_selections",
    "apply_spatial_cls",
    "build_constraint_requirements",
    "build_flexibility_clearing_scorecard",
    "build_locational_clearing",
    "build_locational_clearing_verification_report",
    "build_network_sensitivity",
    "build_provider_registry",
    "select_providers_for_constraint",
    "summarize_provider_registry",
    "write_flexibility_clearing_scorecard",
    "write_locational_clearing_outputs",
    "write_locational_verification_outputs",
]

_MARKET_EXPORTS = {
    "SpatialClsResult",
    "allocate_addition_by_headroom",
    "allocate_reduction",
    "apply_locational_selections",
    "apply_spatial_cls",
    "build_constraint_requirements",
    "build_flexibility_clearing_scorecard",
    "build_locational_clearing",
    "build_locational_clearing_verification_report",
    "build_network_sensitivity",
    "build_provider_registry",
    "select_providers_for_constraint",
    "summarize_provider_registry",
    "write_flexibility_clearing_scorecard",
    "write_locational_clearing_outputs",
    "write_locational_verification_outputs",
}


def __getattr__(name: str):
    if name in _MARKET_EXPORTS:
        value = getattr(import_module("gridalyn.operations.market"), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'gridalyn.operations' has no attribute {name!r}")
