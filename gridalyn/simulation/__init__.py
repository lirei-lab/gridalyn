"""Simulation, powerflow, network-impact, and validation facade."""

from __future__ import annotations

from importlib import import_module

_LAZY_EXPORTS = {
    "PandapowerGridBuilder": (
        "gridalyn.simulation.simulators.powerflow.builder",
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
    "build_graph_snapshot": ("gridalyn.simulation.analytics.network_impact", "build_graph_snapshot"),
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
    "build_surrogate_report": ("gridalyn.simulation.analytics.network_impact", "build_surrogate_report"),
    "build_training_dataset": ("gridalyn.simulation.analytics.network_impact", "build_training_dataset"),
    "build_synthetic_network_from_config": (
        "gridalyn.simulation.simulators.powerflow.synthetic_network",
        "build_synthetic_network_from_config",
    ),
    "build_synthetic_network_from_geojson": (
        "gridalyn.simulation.simulators.powerflow.synthetic_network",
        "build_synthetic_network_from_geojson",
    ),
    "fit_physics_surrogate": ("gridalyn.simulation.analytics.network_impact", "fit_physics_surrogate"),
    "predict_physics_impact": ("gridalyn.simulation.analytics.network_impact", "predict_physics_impact"),
    "run_standard_powerflow_scenario": (
        "gridalyn.simulation.simulators.powerflow.scenarios",
        "run_standard_powerflow_scenario",
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


def __getattr__(name: str):
    if name in _LAZY_EXPORTS:
        module_name, attr_name = _LAZY_EXPORTS[name]
        value = getattr(import_module(module_name), attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'gridalyn.simulation' has no attribute {name!r}")
