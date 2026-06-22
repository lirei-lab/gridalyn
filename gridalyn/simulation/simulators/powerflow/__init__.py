"""Pandapower simulation adapters and synthetic network builders."""

from __future__ import annotations

from importlib import import_module

_LAZY_EXPORTS = {
    "PowerflowMonteCarloRunner": (
        "gridalyn.simulation.simulators.powerflow.runner",
        "PowerflowMonteCarloRunner",
    ),
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
    "apply_standard_powerflow_scenario": (
        "gridalyn.simulation.simulators.powerflow.scenarios",
        "apply_standard_powerflow_scenario",
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
    "build_pandapower_summary": (
        "gridalyn.simulation.simulators.powerflow.artifacts",
        "build_pandapower_summary",
    ),
    "cache_counts": (
        "gridalyn.simulation.simulators.powerflow.topology_cache",
        "cache_counts",
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
    "build_synthetic_network_from_config": (
        "gridalyn.simulation.simulators.powerflow.synthetic_network",
        "build_synthetic_network_from_config",
    ),
    "build_synthetic_network_from_geojson": (
        "gridalyn.simulation.simulators.powerflow.synthetic_network",
        "build_synthetic_network_from_geojson",
    ),
    "build_voltage_control_feeder": (
        "gridalyn.simulation.simulators.powerflow.voltage_control",
        "build_voltage_control_feeder",
    ),
    "configure_headless_matplotlib": (
        "gridalyn.simulation.simulators.powerflow.artifacts",
        "configure_headless_matplotlib",
    ),
    "prepare_synthetic_topology_cache": (
        "gridalyn.simulation.simulators.powerflow.topology_cache",
        "prepare_synthetic_topology_cache",
    ),
    "write_pandapower_element_tables": (
        "gridalyn.simulation.simulators.powerflow.artifacts",
        "write_pandapower_element_tables",
    ),
    "write_powerflow_report": (
        "gridalyn.simulation.simulators.powerflow.artifacts",
        "write_powerflow_report",
    ),
    "validate_building_footprints": (
        "gridalyn.simulation.simulators.powerflow.topology_cache",
        "validate_building_footprints",
    ),
    "TransformerPeakValidationConfig": (
        "gridalyn.simulation.simulators.powerflow.transformer_validation",
        "TransformerPeakValidationConfig",
    ),
    "create_transformer_peak_validation_network": (
        "gridalyn.simulation.simulators.powerflow.transformer_validation",
        "create_transformer_peak_validation_network",
    ),
    "register_transformer_peak_validation_type": (
        "gridalyn.simulation.simulators.powerflow.transformer_validation",
        "register_transformer_peak_validation_type",
    ),
    "validate_transformer_peak_scenarios": (
        "gridalyn.simulation.simulators.powerflow.transformer_validation",
        "validate_transformer_peak_scenarios",
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
    "scenario_to_record": (
        "gridalyn.simulation.simulators.powerflow.scenarios",
        "scenario_to_record",
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
    raise AttributeError(
        f"module 'gridalyn.simulation.simulators.powerflow' has no attribute {name!r}"
    )
