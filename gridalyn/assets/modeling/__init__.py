"""Generative building and asset models for digital-twin studies."""

from __future__ import annotations

from importlib import import_module

_LAZY_EXPORTS = {
    "SyntheticNetworkBuildResult": (
        "gridalyn.assets.modeling.synthetic_network",
        "SyntheticNetworkBuildResult",
    ),
    "BatteryAsset": ("gridalyn.assets.modeling.energy_assets", "BatteryAsset"),
    "PVAsset": ("gridalyn.assets.modeling.energy_assets", "PVAsset"),
    "ProsumerAsset": ("gridalyn.assets.modeling.energy_assets", "ProsumerAsset"),
    "RadialFeederSpec": ("gridalyn.assets.modeling.feeders", "RadialFeederSpec"),
    "ThermalForecast": ("gridalyn.assets.modeling.thermal", "ThermalForecast"),
    "VoltageControlDERSpec": (
        "gridalyn.assets.modeling.voltage_control",
        "VoltageControlDERSpec",
    ),
    "build_asset_registry": ("gridalyn.assets.modeling.assets", "build_asset_registry"),
    "build_radial_pandapower_feeder": (
        "gridalyn.assets.modeling.feeders",
        "build_radial_pandapower_feeder",
    ),
    "build_synthetic_network_from_geojson": (
        "gridalyn.assets.modeling.synthetic_network",
        "build_synthetic_network_from_geojson",
    ),
    "build_thermal_forecast": ("gridalyn.assets.modeling.thermal", "build_thermal_forecast"),
    "build_thermal_forecast_from_ambient": (
        "gridalyn.assets.modeling.thermal",
        "build_thermal_forecast_from_ambient",
    ),
    "build_voltage_control_feeder": (
        "gridalyn.assets.modeling.voltage_control",
        "build_voltage_control_feeder",
    ),
    "apply_battery_dispatch_to_pandapower": (
        "gridalyn.assets.modeling.energy_assets",
        "apply_battery_dispatch_to_pandapower",
    ),
    "apply_pv_generation_to_pandapower": (
        "gridalyn.assets.modeling.energy_assets",
        "apply_pv_generation_to_pandapower",
    ),
    "load_base_inputs": ("gridalyn.assets.modeling.artifacts", "load_base_inputs"),
    "prosumer_assets_to_frame": (
        "gridalyn.assets.modeling.energy_assets",
        "prosumer_assets_to_frame",
    ),
    "summarize_asset_registry": (
        "gridalyn.assets.modeling.assets",
        "summarize_asset_registry",
    ),
    "synthesize_building_model_tables": (
        "gridalyn.assets.modeling.synthesis",
        "synthesize_building_model_tables",
    ),
    "synthesize_scenario_device_tables": (
        "gridalyn.assets.modeling.scenarios",
        "synthesize_scenario_device_tables",
    ),
    "thermal_forecast_metadata": (
        "gridalyn.assets.modeling.thermal",
        "thermal_forecast_metadata",
    ),
    "voltage_control_assets_to_frame": (
        "gridalyn.assets.modeling.voltage_control",
        "voltage_control_assets_to_frame",
    ),
    "write_building_model_artifacts": (
        "gridalyn.assets.modeling.artifacts",
        "write_building_model_artifacts",
    ),
    "write_scenario_model_artifacts": (
        "gridalyn.assets.modeling.scenarios",
        "write_scenario_model_artifacts",
    ),
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str):
    if name in _LAZY_EXPORTS:
        module_name, attr_name = _LAZY_EXPORTS[name]
        value = getattr(import_module(module_name), attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'gridalyn.assets.modeling' has no attribute {name!r}")
