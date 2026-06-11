"""Flexibility operation contracts and services."""

from __future__ import annotations

from gridalyn.operations.flexibility.artifacts import (
    build_operations_catalog,
    clearing_method_from_events,
    infer_dt_h,
    json_default,
    materialize_flexibility_operation_artifacts,
    model_version_id_from_artifacts,
    relpath,
    scenario_frame,
    scenario_ids,
    study_run_id_from_manifest,
    webpath,
)
from gridalyn.operations.flexibility.clearing import run_flexibility_clearing_operation
from gridalyn.operations.flexibility.cls_market import (
    CLSCapacityAllocationResult,
    run_cls_capacity_allocation,
    scenario_label,
)
from gridalyn.operations.flexibility.cls_replay import (
    CLSMarketReplayContext,
    prepare_cls_market_replay_context,
    summarize_stage2_realizations,
)
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
from gridalyn.operations.flexibility.thermal_screening import (
    CongestionForecastResult,
    build_congestion_forecast,
)
from gridalyn.operations.flexibility.validation import (
    CLSOutputConsistencyResult,
    validate_cls_output_consistency,
)

__all__ = [
    "AggregatorPortfolio",
    "CLSCapacityAllocationResult",
    "CLSMarketReplayContext",
    "CLSOutputConsistencyResult",
    "CongestionForecastResult",
    "DispatchInstruction",
    "FlexibilityOperationContext",
    "FlexibilityOperationValidation",
    "FlexibilityOffer",
    "NetworkConstraint",
    "SettlementRecord",
    "build_aggregator_portfolios",
    "build_dispatch_instructions",
    "build_congestion_forecast",
    "build_network_constraint_set",
    "build_operation_context",
    "build_operational_kpi_report",
    "build_operations_catalog",
    "build_provider_offers",
    "build_settlement_records",
    "clearing_method_from_events",
    "infer_dt_h",
    "json_default",
    "materialize_flexibility_operation_artifacts",
    "model_version_id_from_artifacts",
    "prepare_cls_market_replay_context",
    "relpath",
    "run_cls_capacity_allocation",
    "run_flexibility_clearing_operation",
    "scenario_frame",
    "scenario_ids",
    "scenario_label",
    "study_run_id_from_manifest",
    "summarize_network_constraints",
    "summarize_stage2_realizations",
    "validate_flexibility_operation_inputs",
    "validate_cls_output_consistency",
    "webpath",
]
