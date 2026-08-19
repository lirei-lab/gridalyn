"""Platform adapter contracts and implementations."""

from __future__ import annotations

from importlib import import_module

_LAZY_EXPORTS = {
    "BuildingDownloader": ("gridalyn.twin.adapters.geojson", "BuildingDownloader"),
    "build_power_grid_and_network": (
        "gridalyn.twin.adapters.pandapower_builder",
        "build_power_grid_and_network",
    ),
    "CimParquetAdapter": ("gridalyn.twin.adapters.cim", "CimParquetAdapter"),
    "FakeGeoJSONGenerator": ("gridalyn.twin.adapters.geojson", "FakeGeoJSONGenerator"),
    "GeoProcessor": ("gridalyn.twin.adapters.geojson", "GeoProcessor"),
    "ModelAuthoritySet": ("gridalyn.twin.adapters.authority", "ModelAuthoritySet"),
    "ModelProfile": ("gridalyn.twin.adapters.authority", "ModelProfile"),
    "NetworkAdapterDescriptor": (
        "gridalyn.twin.adapters.network",
        "NetworkAdapterDescriptor",
    ),
    "NetworkAdapterRegistration": (
        "gridalyn.twin.adapters.registry",
        "NetworkAdapterRegistration",
    ),
    "NetworkAdapterRegistry": (
        "gridalyn.twin.adapters.registry",
        "NetworkAdapterRegistry",
    ),
    "NetworkExportResult": ("gridalyn.twin.adapters.network", "NetworkExportResult"),
    "NetworkSourceAdapter": ("gridalyn.twin.adapters.network", "NetworkSourceAdapter"),
    "PandapowerGridBuilder": (
        "gridalyn.twin.adapters.pandapower_builder",
        "PandapowerGridBuilder",
    ),
    "SyntheticPandapowerAdapter": (
        "gridalyn.twin.adapters.network",
        "SyntheticPandapowerAdapter",
    ),
    "UnknownNetworkAdapterError": (
        "gridalyn.twin.adapters.registry",
        "UnknownNetworkAdapterError",
    ),
    "build_network_adapter_validation_report": (
        "gridalyn.twin.adapters.validation",
        "build_network_adapter_validation_report",
    ),
    "calculate_area": ("gridalyn.twin.adapters.geojson", "calculate_area"),
    "calculate_centroid": ("gridalyn.twin.adapters.geojson", "calculate_centroid"),
    "default_network_adapter_registry": (
        "gridalyn.twin.adapters.registry",
        "default_network_adapter_registry",
    ),
    "describe_network_source_adapter": (
        "gridalyn.twin.adapters.network",
        "describe_network_source_adapter",
    ),
    "extract_building_data": (
        "gridalyn.twin.adapters.geojson",
        "extract_building_data",
    ),
    "register_network_adapter_extension": (
        "gridalyn.twin.adapters.registry",
        "register_network_adapter_extension",
    ),
    "validate_geojson": ("gridalyn.twin.adapters.geojson", "validate_geojson"),
    "write_network_adapter_validation_report": (
        "gridalyn.twin.adapters.validation",
        "write_network_adapter_validation_report",
    ),
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str):
    if name in _LAZY_EXPORTS:
        module_name, attr_name = _LAZY_EXPORTS[name]
        value = getattr(import_module(module_name), attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'gridalyn.twin.adapters' has no attribute {name!r}")
