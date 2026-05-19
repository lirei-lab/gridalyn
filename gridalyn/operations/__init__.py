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
    "AggregatorPortfolio",
    "DispatchInstruction",
    "FlexibilityOffer",
    "FlexibilityOperationContext",
    "FlexibilityOperationValidation",
    "NetworkConstraint",
    "OperationRun",
    "OperationRunValidation",
    "SettlementRecord",
    "build_aggregator_portfolios",
    "build_dispatch_instructions",
    "build_network_constraint_set",
    "build_operation_context",
    "build_operation_run",
    "build_operational_kpi_report",
    "build_provider_offers",
    "build_settlement_records",
    "validate_operation_run",
    "run_flexibility_clearing_operation",
    "summarize_network_constraints",
    "validate_flexibility_operation_inputs",
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

_FLEXIBILITY_EXPORTS = {
    "AggregatorPortfolio",
    "DispatchInstruction",
    "FlexibilityOffer",
    "FlexibilityOperationContext",
    "FlexibilityOperationValidation",
    "NetworkConstraint",
    "SettlementRecord",
    "build_aggregator_portfolios",
    "build_dispatch_instructions",
    "build_network_constraint_set",
    "build_operation_context",
    "build_operational_kpi_report",
    "build_provider_offers",
    "build_settlement_records",
    "run_flexibility_clearing_operation",
    "summarize_network_constraints",
    "validate_flexibility_operation_inputs",
}

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
    if name in _FLEXIBILITY_EXPORTS:
        value = getattr(import_module("gridalyn.operations.flexibility"), name)
        globals()[name] = value
        return value
    if name in _MARKET_EXPORTS:
        value = getattr(import_module("gridalyn.operations.market"), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'gridalyn.operations' has no attribute {name!r}")
