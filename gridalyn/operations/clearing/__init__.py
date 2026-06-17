"""Canonical clearing surface: selection / allocation / engine_mode modes.

This package is the single home for both flexibility clearing cores, reached
behind the frozen ``gridalyn.operations`` facade (CLEAR-01/02 are resolved
structurally — both cores survive as named modes, neither is deleted):

* :mod:`gridalyn.operations.clearing.selection` — the surrogate/locational
  SELECTION core: the FROZEN ``run_flexibility_clearing_operation`` entry plus
  ``build_locational_clearing`` and the provider registry / sensitivity
  helpers.
* :mod:`gridalyn.operations.clearing.allocation` — the spatial ALLOCATION core
  (``apply_spatial_cls`` and its proportional reduction/headroom helpers).
* :mod:`gridalyn.operations.clearing.engine_mode` — the two-stage Soft/Hard CLS
  MODE (``MarketSimulationEngine`` + ``DSODispatcher`` +
  ``run_cls_capacity_allocation``), the baseline-authoring path.

Resolution is lazy via a concept-keyed ``__getattr__`` map so importing the
package stays cheap and the heavy optional capabilities (scipy / pandapower /
assets datagen) the engine path needs are never pulled in at package import
(Pitfall 5 — lazy purity).
"""

from __future__ import annotations

from importlib import import_module

# Public name -> (module_path, attr). Pure re-export; no eager heavy import.
_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    # --- selection core ---
    "run_flexibility_clearing_operation": (
        "gridalyn.operations.clearing.selection",
        "run_flexibility_clearing_operation",
    ),
    "build_locational_clearing": (
        "gridalyn.operations.clearing.selection",
        "build_locational_clearing",
    ),
    "build_constraint_requirements": (
        "gridalyn.operations.clearing.selection",
        "build_constraint_requirements",
    ),
    "write_locational_clearing_outputs": (
        "gridalyn.operations.clearing.selection",
        "write_locational_clearing_outputs",
    ),
    "build_provider_registry": (
        "gridalyn.operations.clearing.selection",
        "build_provider_registry",
    ),
    "build_network_sensitivity": (
        "gridalyn.operations.clearing.selection",
        "build_network_sensitivity",
    ),
    "select_providers_for_constraint": (
        "gridalyn.operations.clearing.selection",
        "select_providers_for_constraint",
    ),
    "summarize_provider_registry": (
        "gridalyn.operations.clearing.selection",
        "summarize_provider_registry",
    ),
    # --- allocation core ---
    "SpatialClsResult": (
        "gridalyn.operations.clearing.allocation",
        "SpatialClsResult",
    ),
    "allocate_reduction": (
        "gridalyn.operations.clearing.allocation",
        "allocate_reduction",
    ),
    "allocate_addition_by_headroom": (
        "gridalyn.operations.clearing.allocation",
        "allocate_addition_by_headroom",
    ),
    "apply_spatial_cls": (
        "gridalyn.operations.clearing.allocation",
        "apply_spatial_cls",
    ),
    # --- engine_mode core ---
    "MarketSimulationEngine": (
        "gridalyn.operations.clearing.engine_mode",
        "MarketSimulationEngine",
    ),
    "DSODispatcher": (
        "gridalyn.operations.clearing.engine_mode",
        "DSODispatcher",
    ),
    "run_cls_capacity_allocation": (
        "gridalyn.operations.clearing.engine_mode",
        "run_cls_capacity_allocation",
    ),
    "CLSCapacityAllocationResult": (
        "gridalyn.operations.clearing.engine_mode",
        "CLSCapacityAllocationResult",
    ),
    "scenario_label": (
        "gridalyn.operations.clearing.engine_mode",
        "scenario_label",
    ),
    "generate_residential_portfolios": (
        "gridalyn.operations.clearing.engine_mode",
        "generate_residential_portfolios",
    ),
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str) -> object:
    """Lazily resolve a clearing symbol from its mode module.

    Args:
        name: Public attribute requested on ``gridalyn.operations.clearing``.

    Returns:
        The resolved attribute, cached into module globals for free re-access.

    Raises:
        AttributeError: If ``name`` is not a known clearing symbol.
    """
    try:
        module_path, attr = _LAZY_EXPORTS[name]
    except KeyError:
        raise AttributeError(
            f"module 'gridalyn.operations.clearing' has no attribute {name!r}"
        ) from None
    value = getattr(import_module(module_path), attr)
    globals()[name] = value
    return value
