"""Operational services, market clearing, dispatch, and settlement facade."""

from __future__ import annotations

from importlib import import_module

from gridalyn.operations.runs import (  # noqa: F401  (re-exported via __all__)
    OperationRun,
    OperationRunValidation,
    build_operation_run,
    validate_operation_run,
    write_operation_run,
)

# Concept-keyed lazy export map: public name -> (module_path, attr_name).
#
# This single map is the canonical facade contract (DOM-01 / CLEAN-01). It
# replaces the three former source-keyed sets (_FLEXIBILITY_EXPORTS,
# _DER_VOLTAGE_EXPORTS, _MARKET_EXPORTS). In this sub-merge every module_path
# still points at the *current* home module, so this is a pure re-export with
# zero behavior change; later sub-merges re-point individual entries at the
# canonical concept modules without touching this facade's shape.
_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    # --- Domain contracts (canonical home: gridalyn.operations.domain) ---
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
    "build_provider_offers": (
        "gridalyn.operations.domain",
        "build_provider_offers",
    ),
    "build_settlement_records": (
        "gridalyn.operations.domain",
        "build_settlement_records",
    ),
    # --- Operation contracts (canonical home: gridalyn.operations.contracts) ---
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
    # --- Network constraints (canonical home: gridalyn.operations.constraints) ---
    "NetworkConstraint": ("gridalyn.operations.constraints", "NetworkConstraint"),
    "NetworkConstraintModel": (
        "gridalyn.operations.constraints",
        "NetworkConstraintModel",
    ),
    "build_network_constraint_set": (
        "gridalyn.operations.constraints",
        "build_network_constraint_set",
    ),
    "summarize_network_constraints": (
        "gridalyn.operations.constraints",
        "summarize_network_constraints",
    ),
    # --- Settlement / KPI / scorecard (canonical home: settlement) ---
    "build_operational_kpi_report": (
        "gridalyn.operations.settlement",
        "build_operational_kpi_report",
    ),
    "run_flexibility_clearing_operation": (
        "gridalyn.operations.clearing.selection",
        "run_flexibility_clearing_operation",
    ),
    # --- DER-voltage dispatch (out of scope for the merge, still routed) ---
    "DERVoltageDispatchConfig": (
        "gridalyn.operations.der_voltage",
        "DERVoltageDispatchConfig",
    ),
    "DERVoltageDispatchResult": (
        "gridalyn.operations.der_voltage",
        "DERVoltageDispatchResult",
    ),
    "run_der_voltage_dispatch": (
        "gridalyn.operations.der_voltage",
        "run_der_voltage_dispatch",
    ),
    "summarize_der_voltage_dispatch": (
        "gridalyn.operations.der_voltage",
        "summarize_der_voltage_dispatch",
    ),
    "write_der_voltage_dispatch_figure": (
        "gridalyn.operations.der_voltage",
        "write_der_voltage_dispatch_figure",
    ),
    # --- Clearing SELECTION core (canonical home: clearing.selection) ---
    "build_constraint_requirements": (
        "gridalyn.operations.clearing.selection",
        "build_constraint_requirements",
    ),
    "build_locational_clearing": (
        "gridalyn.operations.clearing.selection",
        "build_locational_clearing",
    ),
    "build_network_sensitivity": (
        "gridalyn.operations.clearing.selection",
        "build_network_sensitivity",
    ),
    "build_provider_registry": (
        "gridalyn.operations.clearing.selection",
        "build_provider_registry",
    ),
    "select_providers_for_constraint": (
        "gridalyn.operations.clearing.selection",
        "select_providers_for_constraint",
    ),
    "summarize_provider_registry": (
        "gridalyn.operations.clearing.selection",
        "summarize_provider_registry",
    ),
    "write_locational_clearing_outputs": (
        "gridalyn.operations.clearing.selection",
        "write_locational_clearing_outputs",
    ),
    # --- Clearing ALLOCATION core (canonical home: clearing.allocation) ---
    "SpatialClsResult": ("gridalyn.operations.clearing.allocation", "SpatialClsResult"),
    "allocate_addition_by_headroom": (
        "gridalyn.operations.clearing.allocation",
        "allocate_addition_by_headroom",
    ),
    "allocate_reduction": (
        "gridalyn.operations.clearing.allocation",
        "allocate_reduction",
    ),
    "apply_spatial_cls": (
        "gridalyn.operations.clearing.allocation",
        "apply_spatial_cls",
    ),
    # --- Verification capability (canonical home: verification) ---
    "apply_locational_selections": (
        "gridalyn.operations.verification",
        "apply_locational_selections",
    ),
    "build_flexibility_clearing_scorecard": (
        "gridalyn.operations.settlement",
        "build_flexibility_clearing_scorecard",
    ),
    "build_locational_clearing_verification_report": (
        "gridalyn.operations.verification",
        "build_locational_clearing_verification_report",
    ),
    "build_shadow_report": ("gridalyn.operations.verification", "build_shadow_report"),
    "write_shadow_report": ("gridalyn.operations.verification", "write_shadow_report"),
    "write_flexibility_clearing_scorecard": (
        "gridalyn.operations.settlement",
        "write_flexibility_clearing_scorecard",
    ),
    "write_locational_verification_outputs": (
        "gridalyn.operations.verification",
        "write_locational_verification_outputs",
    ),
    # --- Staged-pipeline API (D-01: study-facing staged building blocks) ---
    "build_congestion_forecast": (
        "gridalyn.operations.replay",
        "build_congestion_forecast",
    ),
    "prepare_cls_market_replay_context": (
        "gridalyn.operations.replay",
        "prepare_cls_market_replay_context",
    ),
    "summarize_stage2_realizations": (
        "gridalyn.operations.replay",
        "summarize_stage2_realizations",
    ),
    "run_cls_capacity_allocation": (
        "gridalyn.operations.clearing.engine_mode",
        "run_cls_capacity_allocation",
    ),
    "validate_cls_output_consistency": (
        "gridalyn.operations.verification",
        "validate_cls_output_consistency",
    ),
    "materialize_flexibility_operation_artifacts": (
        "gridalyn.operations.artifacts",
        "materialize_flexibility_operation_artifacts",
    ),
    # --- Prosumer real-time market (canonical home: prosumer_realtime, D-01) ---
    # Deferred so the leaf-module ``import pandapower`` never fires at
    # ``import gridalyn.operations`` (boundary purity, T-05-12).
    "ProsumerRealtimeMarketConfig": (
        "gridalyn.operations.prosumer_realtime",
        "ProsumerRealtimeMarketConfig",
    ),
    "ProsumerRealtimeMarketResult": (
        "gridalyn.operations.prosumer_realtime",
        "ProsumerRealtimeMarketResult",
    ),
    "build_interval_forecast": (
        "gridalyn.operations.prosumer_realtime",
        "build_interval_forecast",
    ),
    "build_prosumer_realtime_market_summary": (
        "gridalyn.operations.prosumer_realtime",
        "build_prosumer_realtime_market_summary",
    ),
    "clear_prosumer_interval": (
        "gridalyn.operations.prosumer_realtime",
        "clear_prosumer_interval",
    ),
    "run_prosumer_powerflow": (
        "gridalyn.operations.prosumer_realtime",
        "run_prosumer_powerflow",
    ),
    "run_prosumer_realtime_market": (
        "gridalyn.operations.prosumer_realtime",
        "run_prosumer_realtime_market",
    ),
    "write_prosumer_market_dispatch_figure": (
        "gridalyn.operations.prosumer_realtime",
        "write_prosumer_market_dispatch_figure",
    ),
}

# Eager names from runs.py (stdlib-light) plus the lazily-routed public surface.
_EAGER_EXPORTS = [
    "OperationRun",
    "OperationRunValidation",
    "build_operation_run",
    "validate_operation_run",
    "write_operation_run",
]

__all__ = sorted(_LAZY_EXPORTS) + _EAGER_EXPORTS


def __getattr__(name: str):
    """Lazily resolve a public operations symbol from its concept module.

    Args:
        name: Public attribute requested on ``gridalyn.operations``.

    Returns:
        The resolved attribute, cached into module globals for free re-access.

    Raises:
        AttributeError: If ``name`` is not a known public operations symbol.
    """
    try:
        module_path, attr = _LAZY_EXPORTS[name]
    except KeyError:
        raise AttributeError(
            f"module 'gridalyn.operations' has no attribute {name!r}"
        ) from None
    value = getattr(import_module(module_path), attr)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """List the module namespace plus every lazily exported public name.

    Returns:
        Sorted names, so ``dir()`` and :func:`inspect.getmembers` see the
        lazy exports that ``__getattr__`` resolves on demand.
    """
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
