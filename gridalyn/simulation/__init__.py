"""Simulation, powerflow, network-impact, and validation facade."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "PowerFlowBackend": (
        "gridalyn.simulation.backends",
        "PowerFlowBackend",
    ),
    "PowerFlowBackendDescriptor": (
        "gridalyn.simulation.backends",
        "PowerFlowBackendDescriptor",
    ),
    "PowerFlowBackendRegistry": (
        "gridalyn.simulation.backends",
        "PowerFlowBackendRegistry",
    ),
    "UnknownPowerFlowBackendError": (
        "gridalyn.simulation.backends",
        "UnknownPowerFlowBackendError",
    ),
    "default_powerflow_backend_registry": (
        "gridalyn.simulation.backends",
        "default_powerflow_backend_registry",
    ),
    "resolve_powerflow_backend": (
        "gridalyn.simulation.backends",
        "resolve_powerflow_backend",
    ),
    "solve_power_flow": (
        "gridalyn.simulation.backends",
        "solve_power_flow",
    ),
    "register_powerflow_backend_extension": (
        "gridalyn.simulation.backends",
        "register_powerflow_backend_extension",
    ),
    # Resolved from ``gridalyn.twin.observation``, which owns the contract
    # since Phase 11. Pointing at the deprecated
    # ``gridalyn.simulation.observation`` shim instead would make every
    # ``from gridalyn.simulation import NetworkObservation`` emit a
    # DeprecationWarning for an import that is not deprecated.
    "NetworkObservation": (
        "gridalyn.twin.observation",
        "NetworkObservation",
    ),
    "observe_network": (
        "gridalyn.twin.observation",
        "observe_network",
    ),
    "ErrorBound": (
        "gridalyn.simulation.surrogates",
        "ErrorBound",
    ),
    "Surrogate": (
        "gridalyn.simulation.surrogates",
        "Surrogate",
    ),
    "SurrogateDescriptor": (
        "gridalyn.simulation.surrogates",
        "SurrogateDescriptor",
    ),
    "SurrogateRegistry": (
        "gridalyn.simulation.surrogates",
        "SurrogateRegistry",
    ),
    "UnboundedSurrogateError": (
        "gridalyn.simulation.surrogates",
        "UnboundedSurrogateError",
    ),
    "UnknownSurrogateError": (
        "gridalyn.simulation.surrogates",
        "UnknownSurrogateError",
    ),
    "default_surrogate_registry": (
        "gridalyn.simulation.surrogates",
        "default_surrogate_registry",
    ),
    "register_surrogate_extension": (
        "gridalyn.simulation.surrogates",
        "register_surrogate_extension",
    ),
    "register_policy_extension": (
        "gridalyn.simulation.policies",
        "register_policy_extension",
    ),
    "measure_relief_error_bound": (
        "gridalyn.simulation.surrogates",
        "measure_relief_error_bound",
    ),
    "registered_error_bounds": (
        "gridalyn.simulation.surrogates",
        "registered_error_bounds",
    ),
    "resolve_surrogate": (
        "gridalyn.simulation.surrogates",
        "resolve_surrogate",
    ),
    "unmeasured_error_bound": (
        "gridalyn.simulation.surrogates",
        "unmeasured_error_bound",
    ),
    "PandapowerGridBuilder": (
        "gridalyn.twin.adapters.pandapower_builder",
        "PandapowerGridBuilder",
    ),
    "SyntheticNetworkBuildResult": (
        "gridalyn.simulation.simulators.powerflow.synthetic_network",
        "SyntheticNetworkBuildResult",
    ),
    "StandardPowerflowScenario": (
        "gridalyn.simulation.simulators.powerflow.scenarios",
        "StandardPowerflowScenario",
    ),
    "LightSimPowerflowAdapter": (
        "gridalyn.simulation.simulators.lightsim",
        "LightSimPowerflowAdapter",
    ),
    "VoltageControlEnvironment": (
        "gridalyn.simulation.environments",
        "VoltageControlEnvironment",
    ),
    "VoltageControlEnvironmentSpec": (
        "gridalyn.simulation.environments",
        "VoltageControlEnvironmentSpec",
    ),
    "TabularVoltageControlConfig": (
        "gridalyn.simulation.control",
        "TabularVoltageControlConfig",
    ),
    "TabularVoltageControlResult": (
        "gridalyn.simulation.control",
        "TabularVoltageControlResult",
    ),
    "TransformerPeakValidationConfig": (
        "gridalyn.simulation.simulators.powerflow.transformer_validation",
        "TransformerPeakValidationConfig",
    ),
    "LineSizingResult": (
        "gridalyn.simulation.analytics.line_sizing",
        "LineSizingResult",
    ),
    "analyze_line_sizing": (
        "gridalyn.simulation.analytics.line_sizing",
        "analyze_line_sizing",
    ),
    "analyze_synthetic_line_sizing": (
        "gridalyn.simulation.analytics.line_sizing",
        "analyze_synthetic_line_sizing",
    ),
    "apply_battery_dispatch_to_pandapower": (
        "gridalyn.simulation.simulators.powerflow.energy_assets",
        "apply_battery_dispatch_to_pandapower",
    ),
    "apply_der_dispatch_setpoints_to_pandapower": (
        "gridalyn.simulation.simulators.powerflow.der_dispatch",
        "apply_der_dispatch_setpoints_to_pandapower",
    ),
    "apply_pv_generation_to_pandapower": (
        "gridalyn.simulation.simulators.powerflow.energy_assets",
        "apply_pv_generation_to_pandapower",
    ),
    "apply_standard_powerflow_scenario": (
        "gridalyn.simulation.simulators.powerflow.scenarios",
        "apply_standard_powerflow_scenario",
    ),
    "build_pandapower_summary": (
        "gridalyn.simulation.simulators.powerflow.artifacts",
        "build_pandapower_summary",
    ),
    "build_ieee33_benchmark_feeder": (
        "gridalyn.simulation.simulators.powerflow.benchmarks",
        "build_ieee33_benchmark_feeder",
    ),
    "build_der_dispatch_pandapower_network": (
        "gridalyn.simulation.simulators.powerflow.der_dispatch",
        "build_der_dispatch_pandapower_network",
    ),
    "build_radial_pandapower_feeder": (
        "gridalyn.simulation.simulators.powerflow.feeders",
        "build_radial_pandapower_feeder",
    ),
    "build_voltage_control_feeder": (
        "gridalyn.simulation.simulators.powerflow.voltage_control",
        "build_voltage_control_feeder",
    ),
    "configure_headless_matplotlib": (
        "gridalyn.simulation.simulators.powerflow.artifacts",
        "configure_headless_matplotlib",
    ),
    "build_graph_snapshot": (
        "gridalyn.simulation.analytics.network_impact",
        "build_graph_snapshot",
    ),
    "build_network_impact_catalog": (
        "gridalyn.simulation.analytics.network_impact",
        "build_network_impact_catalog",
    ),
    "build_network_impact_verification_report": (
        "gridalyn.simulation.analytics.network_impact",
        "build_network_impact_verification_report",
    ),
    "build_physics_surrogate_report": (
        "gridalyn.simulation.analytics.network_impact",
        "build_physics_surrogate_report",
    ),
    "build_provider_impact_predictions": (
        "gridalyn.simulation.analytics.network_impact",
        "build_provider_impact_predictions",
    ),
    "build_surrogate_report": (
        "gridalyn.simulation.analytics.network_impact",
        "build_surrogate_report",
    ),
    "build_training_dataset": (
        "gridalyn.simulation.analytics.network_impact",
        "build_training_dataset",
    ),
    "build_synthetic_network_from_config": (
        "gridalyn.simulation.simulators.powerflow.synthetic_network",
        "build_synthetic_network_from_config",
    ),
    "VALIDATION_FILENAME": (
        "gridalyn.simulation.simulators.powerflow.synthetic_network",
        "VALIDATION_FILENAME",
    ),
    "build_synthetic_network_from_geojson": (
        "gridalyn.simulation.simulators.powerflow.synthetic_network",
        "build_synthetic_network_from_geojson",
    ),
    "fit_physics_surrogate": (
        "gridalyn.simulation.analytics.network_impact",
        "fit_physics_surrogate",
    ),
    "predict_physics_impact": (
        "gridalyn.simulation.analytics.network_impact",
        "predict_physics_impact",
    ),
    "prepare_synthetic_topology_cache": (
        "gridalyn.simulation.simulators.powerflow.topology_cache",
        "prepare_synthetic_topology_cache",
    ),
    "run_standard_powerflow_scenario": (
        "gridalyn.simulation.simulators.powerflow.scenarios",
        "run_standard_powerflow_scenario",
    ),
    "select_line_std_type": (
        "gridalyn.simulation.simulators.powerflow.line_sizing_select",
        "select_line_std_type",
    ),
    "size_lines_load_aware": (
        "gridalyn.simulation.simulators.powerflow.line_sizing_select",
        "size_lines_load_aware",
    ),
    "summarize_tabular_voltage_control": (
        "gridalyn.simulation.control",
        "summarize_tabular_voltage_control",
    ),
    "scenario_to_record": (
        "gridalyn.simulation.simulators.powerflow.scenarios",
        "scenario_to_record",
    ),
    "write_network_impact_catalog": (
        "gridalyn.simulation.analytics.network_impact",
        "write_network_impact_catalog",
    ),
    "write_pandapower_element_tables": (
        "gridalyn.simulation.simulators.powerflow.artifacts",
        "write_pandapower_element_tables",
    ),
    "train_tabular_voltage_controller": (
        "gridalyn.simulation.control",
        "train_tabular_voltage_controller",
    ),
    "validate_transformer_peak_scenarios": (
        "gridalyn.simulation.simulators.powerflow.transformer_validation",
        "validate_transformer_peak_scenarios",
    ),
    "write_tabular_voltage_control_figure": (
        "gridalyn.simulation.control",
        "write_tabular_voltage_control_figure",
    ),
    "write_powerflow_report": (
        "gridalyn.simulation.simulators.powerflow.artifacts",
        "write_powerflow_report",
    ),
    "write_voltage_profile_figure": (
        "gridalyn.simulation.simulators.powerflow.artifacts",
        "write_voltage_profile_figure",
    ),
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    """Lazily resolve a simulation symbol from its implementation module.

    Args:
        name: Public attribute requested on ``gridalyn.simulation``.

    Returns:
        The resolved attribute, cached into module globals for free re-access.

    Raises:
        AttributeError: If ``name`` is not a known simulation symbol.
    """
    if name in _LAZY_EXPORTS:
        module_name, attr_name = _LAZY_EXPORTS[name]
        value = getattr(import_module(module_name), attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'gridalyn.simulation' has no attribute {name!r}")


def __dir__() -> list[str]:
    """List the module namespace plus every lazily exported public name.

    Returns:
        Sorted names, so ``dir()`` and :func:`inspect.getmembers` see the
        lazy exports that ``__getattr__`` resolves on demand.
    """
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
