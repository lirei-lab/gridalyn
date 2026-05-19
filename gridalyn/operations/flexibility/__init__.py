"""Flexibility operation contracts and services."""

from __future__ import annotations

from gridalyn.operations.flexibility.clearing import run_flexibility_clearing_operation
from gridalyn.operations.flexibility.contracts import (
    FlexibilityOperationContext,
    FlexibilityOperationValidation,
    build_operation_context,
    validate_flexibility_operation_inputs,
)
from gridalyn.operations.flexibility.domain import (
    AggregatorPortfolio,
    DispatchInstruction,
    FlexibilityOffer,
    SettlementRecord,
    build_aggregator_portfolios,
    build_dispatch_instructions,
    build_provider_offers,
    build_settlement_records,
)
from gridalyn.operations.flexibility.constraints import (
    NetworkConstraint,
    build_network_constraint_set,
    summarize_network_constraints,
)
from gridalyn.operations.flexibility.kpis import build_operational_kpi_report

__all__ = [
    "AggregatorPortfolio",
    "DispatchInstruction",
    "FlexibilityOperationContext",
    "FlexibilityOperationValidation",
    "FlexibilityOffer",
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
]
