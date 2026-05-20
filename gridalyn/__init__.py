"""Gridalyn public Python API."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "assets",
    "foundation",
    "interfaces",
    "operations",
    "PowerGridGraph",
    "projects",
    "simulation",
    "twin",
    "NetworkAnalyzer",
    "PandapowerGridBuilder",
    "GridPlotter",
    "BatteryAsset",
    "get_dataset_path",
    "list_available_datasets",
    "LightSimPowerflowAdapter",
    "load_project",
    "RadialFeederSpec",
    "project_sense_check",
    "project_verify",
    "run_workflow",
    "VoltageControlDERSpec",
    "VoltageControlEnvironment",
    "VoltageControlEnvironmentSpec",
    "validate_project",
    "build_operation_run",
    "build_radial_pandapower_feeder",
    "build_synthetic_network_from_geojson",
    "build_voltage_control_feeder",
    "SyntheticNetworkBuildResult",
    "validate_operation_run",
]

_LAZY_EXPORTS = {
    "assets": ("gridalyn.assets", "assets"),
    "foundation": ("gridalyn.foundation", "foundation"),
    "interfaces": ("gridalyn.interfaces", "interfaces"),
    "operations": ("gridalyn.operations", "operations"),
    "projects": ("gridalyn.projects", "projects"),
    "simulation": ("gridalyn.simulation", "simulation"),
    "twin": ("gridalyn.twin", "twin"),
    "PowerGridGraph": ("gridalyn.twin.core.graph", "PowerGridGraph"),
    "NetworkAnalyzer": ("gridalyn.twin.core.topology", "NetworkAnalyzer"),
    "PandapowerGridBuilder": ("gridalyn.simulation.simulators.powerflow.builder", "PandapowerGridBuilder"),
    "GridPlotter": ("gridalyn.interfaces.viz.interactive", "GridPlotter"),
    "BatteryAsset": ("gridalyn.assets", "BatteryAsset"),
    "get_dataset_path": ("gridalyn.foundation.data", "get_dataset_path"),
    "list_available_datasets": ("gridalyn.foundation.data", "list_available_datasets"),
    "LightSimPowerflowAdapter": ("gridalyn.simulation", "LightSimPowerflowAdapter"),
    "load_project": ("gridalyn.foundation.platform.projects", "load_project"),
    "RadialFeederSpec": ("gridalyn.assets", "RadialFeederSpec"),
    "project_sense_check": ("gridalyn.foundation.platform.projects", "project_sense_check"),
    "project_verify": ("gridalyn.foundation.platform.projects", "project_verify"),
    "run_workflow": ("gridalyn.foundation.platform.projects", "run_workflow"),
    "VoltageControlDERSpec": ("gridalyn.assets", "VoltageControlDERSpec"),
    "VoltageControlEnvironment": ("gridalyn.simulation", "VoltageControlEnvironment"),
    "VoltageControlEnvironmentSpec": ("gridalyn.simulation", "VoltageControlEnvironmentSpec"),
    "validate_project": ("gridalyn.foundation.platform.projects", "validate_project"),
    "build_operation_run": ("gridalyn.operations", "build_operation_run"),
    "build_radial_pandapower_feeder": (
        "gridalyn.assets",
        "build_radial_pandapower_feeder",
    ),
    "build_synthetic_network_from_geojson": (
        "gridalyn.assets.modeling.synthetic_network",
        "build_synthetic_network_from_geojson",
    ),
    "build_voltage_control_feeder": ("gridalyn.assets", "build_voltage_control_feeder"),
    "SyntheticNetworkBuildResult": (
        "gridalyn.assets.modeling.synthetic_network",
        "SyntheticNetworkBuildResult",
    ),
    "validate_operation_run": ("gridalyn.operations", "validate_operation_run"),
}


def __getattr__(name: str):
    if name in _LAZY_EXPORTS:
        module_name, attr_name = _LAZY_EXPORTS[name]
        module = import_module(module_name)
        value = module if attr_name == name and module_name.endswith(f".{name}") else getattr(module, attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'gridalyn' has no attribute {name!r}")
