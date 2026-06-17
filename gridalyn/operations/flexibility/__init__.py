"""Flexibility operation contracts and services (legacy package facade).

The domain/contract/constraint types now live in the canonical concept modules
:mod:`gridalyn.operations.domain`, :mod:`gridalyn.operations.contracts`, and
:mod:`gridalyn.operations.constraints`. This package remains importable as a
quiet legacy facade: package-root names (used by the ``flexibility_cls`` study
scripts) resolve lazily to the IDENTICAL canonical object. The moved
domain/contract/constraint names emit a quiet :class:`DeprecationWarning`; the
still-here clearing/replay/artifact names resolve without a warning.
"""

from __future__ import annotations

import warnings
from importlib import import_module

# Public name -> (module_path, attr). Moved names point at the canonical concept
# modules (CLEAN-01: identical object); the rest stay on their current homes.
_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    # --- moved to canonical concept modules (quiet DeprecationWarning) ---
    "AggregatorPortfolio": ("gridalyn.operations.domain", "AggregatorPortfolio"),
    "DispatchInstruction": ("gridalyn.operations.domain", "DispatchInstruction"),
    "FlexibilityOffer": ("gridalyn.operations.domain", "FlexibilityOffer"),
    "SettlementRecord": ("gridalyn.operations.domain", "SettlementRecord"),
    "build_aggregator_portfolios": (
        "gridalyn.operations.domain",
        "build_aggregator_portfolios",
    ),
    "build_dispatch_instructions": (
        "gridalyn.operations.domain",
        "build_dispatch_instructions",
    ),
    "build_provider_offers": ("gridalyn.operations.domain", "build_provider_offers"),
    "build_settlement_records": (
        "gridalyn.operations.domain",
        "build_settlement_records",
    ),
    "FlexibilityOperationContext": (
        "gridalyn.operations.contracts",
        "FlexibilityOperationContext",
    ),
    "FlexibilityOperationValidation": (
        "gridalyn.operations.contracts",
        "FlexibilityOperationValidation",
    ),
    "build_operation_context": (
        "gridalyn.operations.contracts",
        "build_operation_context",
    ),
    "validate_flexibility_operation_inputs": (
        "gridalyn.operations.contracts",
        "validate_flexibility_operation_inputs",
    ),
    "NetworkConstraint": ("gridalyn.operations.constraints", "NetworkConstraint"),
    "build_network_constraint_set": (
        "gridalyn.operations.constraints",
        "build_network_constraint_set",
    ),
    "summarize_network_constraints": (
        "gridalyn.operations.constraints",
        "summarize_network_constraints",
    ),
    # --- still living in the flexibility package (no deprecation) ---
    "build_operations_catalog": (
        "gridalyn.operations.flexibility.artifacts",
        "build_operations_catalog",
    ),
    "clearing_method_from_events": (
        "gridalyn.operations.flexibility.artifacts",
        "clearing_method_from_events",
    ),
    "infer_dt_h": ("gridalyn.operations.flexibility.artifacts", "infer_dt_h"),
    "json_default": ("gridalyn.operations.flexibility.artifacts", "json_default"),
    "materialize_flexibility_operation_artifacts": (
        "gridalyn.operations.flexibility.artifacts",
        "materialize_flexibility_operation_artifacts",
    ),
    "model_version_id_from_artifacts": (
        "gridalyn.operations.flexibility.artifacts",
        "model_version_id_from_artifacts",
    ),
    "relpath": ("gridalyn.operations.flexibility.artifacts", "relpath"),
    "scenario_frame": (
        "gridalyn.operations.flexibility.artifacts",
        "scenario_frame",
    ),
    "scenario_ids": ("gridalyn.operations.flexibility.artifacts", "scenario_ids"),
    "study_run_id_from_manifest": (
        "gridalyn.operations.flexibility.artifacts",
        "study_run_id_from_manifest",
    ),
    "webpath": ("gridalyn.operations.flexibility.artifacts", "webpath"),
    "run_flexibility_clearing_operation": (
        "gridalyn.operations.flexibility.clearing",
        "run_flexibility_clearing_operation",
    ),
    "CLSCapacityAllocationResult": (
        "gridalyn.operations.flexibility.cls_market",
        "CLSCapacityAllocationResult",
    ),
    "run_cls_capacity_allocation": (
        "gridalyn.operations.flexibility.cls_market",
        "run_cls_capacity_allocation",
    ),
    "scenario_label": (
        "gridalyn.operations.flexibility.cls_market",
        "scenario_label",
    ),
    "CLSMarketReplayContext": (
        "gridalyn.operations.flexibility.cls_replay",
        "CLSMarketReplayContext",
    ),
    "prepare_cls_market_replay_context": (
        "gridalyn.operations.flexibility.cls_replay",
        "prepare_cls_market_replay_context",
    ),
    "summarize_stage2_realizations": (
        "gridalyn.operations.flexibility.cls_replay",
        "summarize_stage2_realizations",
    ),
    "build_operational_kpi_report": (
        "gridalyn.operations.flexibility.kpis",
        "build_operational_kpi_report",
    ),
    "CongestionForecastResult": (
        "gridalyn.operations.flexibility.thermal_screening",
        "CongestionForecastResult",
    ),
    "build_congestion_forecast": (
        "gridalyn.operations.flexibility.thermal_screening",
        "build_congestion_forecast",
    ),
    "CLSOutputConsistencyResult": (
        "gridalyn.operations.flexibility.validation",
        "CLSOutputConsistencyResult",
    ),
    "validate_cls_output_consistency": (
        "gridalyn.operations.flexibility.validation",
        "validate_cls_output_consistency",
    ),
}

# Names that moved to canonical concept modules — accessing them via this legacy
# package facade emits a quiet DeprecationWarning (CLEAN-01).
_DEPRECATED = {
    "AggregatorPortfolio",
    "DispatchInstruction",
    "FlexibilityOffer",
    "SettlementRecord",
    "build_aggregator_portfolios",
    "build_dispatch_instructions",
    "build_provider_offers",
    "build_settlement_records",
    "FlexibilityOperationContext",
    "FlexibilityOperationValidation",
    "build_operation_context",
    "validate_flexibility_operation_inputs",
    "NetworkConstraint",
    "build_network_constraint_set",
    "summarize_network_constraints",
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str) -> object:
    """Lazily resolve a public flexibility symbol from its current home.

    Args:
        name: Public attribute requested on ``gridalyn.operations.flexibility``.

    Returns:
        The resolved attribute, cached into module globals for free re-access.
        Names that moved to the canonical concept modules emit a quiet
        :class:`DeprecationWarning` and resolve to the IDENTICAL object.

    Raises:
        AttributeError: If ``name`` is not a known public flexibility symbol.
    """
    try:
        module_path, attr = _LAZY_EXPORTS[name]
    except KeyError:
        raise AttributeError(
            f"module 'gridalyn.operations.flexibility' has no attribute {name!r}"
        ) from None
    if name in _DEPRECATED:
        warnings.warn(
            f"import {name} from {module_path} "
            f"(gridalyn.operations.flexibility.{name} is deprecated)",
            DeprecationWarning,
            stacklevel=2,
        )
    value = getattr(import_module(module_path), attr)
    globals()[name] = value
    return value
