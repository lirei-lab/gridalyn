"""Gridalyn public Python API."""

from __future__ import annotations

import warnings
from importlib import import_module

from gridalyn.foundation.platform.compatibility import register_compat_module_aliases


register_compat_module_aliases(__name__)

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

_LEGACY_DATASET_EXPORTS = {"PowerGridDataset", "CIMDataset", "GeoJSONDataset"}
_LAZY_EXPORTS = {
    "assets": ("gridalyn.assets", "assets"),
    "foundation": ("gridalyn.foundation", "foundation"),
    "interfaces": ("gridalyn.interfaces", "interfaces"),
    "operations": ("gridalyn.operations", "operations"),
    "projects": ("gridalyn.projects", "projects"),
    "simulation": ("gridalyn.simulation", "simulation"),
    "twin": ("gridalyn.twin", "twin"),
    "PowerGridGraph": ("gridalyn.core.graph", "PowerGridGraph"),
    "NetworkAnalyzer": ("gridalyn.core.topology", "NetworkAnalyzer"),
    "PandapowerGridBuilder": ("gridalyn.simulators.powerflow.builder", "PandapowerGridBuilder"),
    "GridPlotter": ("gridalyn.viz.interactive", "GridPlotter"),
    "BatteryAsset": ("gridalyn.assets", "BatteryAsset"),
    "get_dataset_path": ("gridalyn.data", "get_dataset_path"),
    "list_available_datasets": ("gridalyn.data", "list_available_datasets"),
    "LightSimPowerflowAdapter": ("gridalyn.simulation", "LightSimPowerflowAdapter"),
    "load_project": ("gridalyn.platform.projects", "load_project"),
    "RadialFeederSpec": ("gridalyn.assets", "RadialFeederSpec"),
    "project_sense_check": ("gridalyn.platform.projects", "project_sense_check"),
    "project_verify": ("gridalyn.platform.projects", "project_verify"),
    "run_workflow": ("gridalyn.platform.projects", "run_workflow"),
    "VoltageControlDERSpec": ("gridalyn.assets", "VoltageControlDERSpec"),
    "VoltageControlEnvironment": ("gridalyn.simulation", "VoltageControlEnvironment"),
    "VoltageControlEnvironmentSpec": ("gridalyn.simulation", "VoltageControlEnvironmentSpec"),
    "validate_project": ("gridalyn.platform.projects", "validate_project"),
    "build_operation_run": ("gridalyn.operations", "build_operation_run"),
    "build_radial_pandapower_feeder": (
        "gridalyn.assets",
        "build_radial_pandapower_feeder",
    ),
    "build_synthetic_network_from_geojson": (
        "gridalyn.modeling.synthetic_network",
        "build_synthetic_network_from_geojson",
    ),
    "build_voltage_control_feeder": ("gridalyn.assets", "build_voltage_control_feeder"),
    "SyntheticNetworkBuildResult": (
        "gridalyn.modeling.synthetic_network",
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
    if name in _LEGACY_DATASET_EXPORTS:
        warnings.warn(
            f"gridalyn.{name} is a legacy dataset stub. Use "
            "gridalyn.data.get_dataset_path/list_available_datasets for demo data "
            "or define project datasets through project.yaml.",
            DeprecationWarning,
            stacklevel=2,
        )
        from gridalyn.data import datasets

        return getattr(datasets, name)
    raise AttributeError(f"module 'gridalyn' has no attribute {name!r}")
