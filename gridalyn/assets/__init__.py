"""Asset, building, load, EV, DER, and flexibility model facade."""

from __future__ import annotations

from importlib import import_module

_LAZY_EXPORTS = {
    "BuildingDownloader": ("gridalyn.twin.adapters", "BuildingDownloader"),
    "BatteryAsset": ("gridalyn.assets.modeling", "BatteryAsset"),
    "DERDispatchAsset": ("gridalyn.assets.modeling", "DERDispatchAsset"),
    "IEEE_33_BUS_BENCHMARK": ("gridalyn.assets.modeling", "IEEE_33_BUS_BENCHMARK"),
    "IeeeBenchmarkFeederSpec": ("gridalyn.assets.modeling", "IeeeBenchmarkFeederSpec"),
    "FakeGeoJSONGenerator": ("gridalyn.twin.adapters", "FakeGeoJSONGenerator"),
    "GeoProcessor": ("gridalyn.twin.adapters", "GeoProcessor"),
    "PVAsset": ("gridalyn.assets.modeling", "PVAsset"),
    "ProsumerAsset": ("gridalyn.assets.modeling", "ProsumerAsset"),
    "RadialFeederSpec": ("gridalyn.assets.modeling", "RadialFeederSpec"),
    "ThermalForecast": ("gridalyn.assets.modeling", "ThermalForecast"),
    "TransformerThermalModel": ("gridalyn.assets.modeling", "TransformerThermalModel"),
    "VoltageControlDERSpec": ("gridalyn.assets.modeling", "VoltageControlDERSpec"),
    "build_asset_registry": ("gridalyn.assets.modeling", "build_asset_registry"),
    "build_thermal_forecast": ("gridalyn.assets.datagen", "build_thermal_forecast"),
    "build_thermal_forecast_from_ambient": (
        "gridalyn.assets.modeling",
        "build_thermal_forecast_from_ambient",
    ),
    "der_dispatch_assets_to_frame": (
        "gridalyn.assets.modeling",
        "der_dispatch_assets_to_frame",
    ),
    "generate_residential_load_profiles": (
        "gridalyn.assets.datagen",
        "generate_residential_load_profiles",
    ),
    "calculate_area": ("gridalyn.twin.adapters", "calculate_area"),
    "calculate_centroid": ("gridalyn.twin.adapters", "calculate_centroid"),
    "extract_building_data": ("gridalyn.twin.adapters", "extract_building_data"),
    "load_base_inputs": ("gridalyn.assets.modeling", "load_base_inputs"),
    "prosumer_assets_to_frame": (
        "gridalyn.assets.modeling",
        "prosumer_assets_to_frame",
    ),
    "summarize_asset_registry": (
        "gridalyn.assets.modeling",
        "summarize_asset_registry",
    ),
    "synthesize_building_model_tables": (
        "gridalyn.assets.modeling",
        "synthesize_building_model_tables",
    ),
    "synthesize_scenario_device_tables": (
        "gridalyn.assets.modeling",
        "synthesize_scenario_device_tables",
    ),
    "thermal_forecast_metadata": (
        "gridalyn.assets.modeling",
        "thermal_forecast_metadata",
    ),
    "validate_geojson": ("gridalyn.twin.adapters", "validate_geojson"),
    "voltage_control_assets_to_frame": (
        "gridalyn.assets.modeling",
        "voltage_control_assets_to_frame",
    ),
    "validate_radial_feeder_spec": (
        "gridalyn.assets.modeling",
        "validate_radial_feeder_spec",
    ),
    "validate_der_dispatch_assets": (
        "gridalyn.assets.modeling",
        "validate_der_dispatch_assets",
    ),
    "validate_voltage_control_der": (
        "gridalyn.assets.modeling",
        "validate_voltage_control_der",
    ),
    "write_building_model_artifacts": (
        "gridalyn.assets.modeling",
        "write_building_model_artifacts",
    ),
    "write_scenario_model_artifacts": (
        "gridalyn.assets.modeling",
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
    raise AttributeError(f"module 'gridalyn.assets' has no attribute {name!r}")


def __dir__() -> list[str]:
    """List the module namespace plus every lazily exported public name.

    Returns:
        Sorted names, so ``dir()`` and :func:`inspect.getmembers` see the
        lazy exports that ``__getattr__`` resolves on demand.
    """
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
