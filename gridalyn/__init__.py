"""Gridalyn public Python API."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "assets",
    "foundation",
    "interfaces",
    "operations",
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
    "ReportMetadata",
    "aggregate_load_multipliers",
    "generate_residential_load_profiles",
    "scale_profiles_to_peaks",
    "init_project",
    "load_der_dispatch_assets",
    "load_generated_bus_loads_mw",
    "load_generated_load_multipliers",
    "load_generated_load_profiles",
    "load_numeric_profile_array",
    "load_project",
    "load_prosumer_assets",
    "load_radial_feeder_spec",
    "load_voltage_control_der_spec",
    "plan_project",
    "RadialFeederSpec",
    "project_input",
    "project_regression",
    "project_script",
    "project_sense_check",
    "project_status",
    "project_verify",
    "run_workflow",
    "write_report",
    "VoltageControlDERSpec",
    "VoltageControlEnvironment",
    "VoltageControlEnvironmentSpec",
    "validate_project",
    "build_operation_run",
    "build_radial_pandapower_feeder",
    "build_synthetic_network_from_geojson",
    "build_voltage_control_feeder",
    "SyntheticNetworkBuildResult",
    "build_ieee33_benchmark_feeder",
    "validate_operation_run",
    "write_powerflow_report",
    "write_voltage_profile_figure",
]

_LAZY_EXPORTS = {
    "assets": ("gridalyn.assets", "assets"),
    "foundation": ("gridalyn.foundation", "foundation"),
    "interfaces": ("gridalyn.interfaces", "interfaces"),
    "operations": ("gridalyn.operations", "operations"),
    "projects": ("gridalyn.projects", "projects"),
    "simulation": ("gridalyn.simulation", "simulation"),
    "twin": ("gridalyn.twin", "twin"),
    "NetworkAnalyzer": ("gridalyn.twin.core.topology", "NetworkAnalyzer"),
    "PandapowerGridBuilder": (
        "gridalyn.simulation.simulators.powerflow.builder",
        "PandapowerGridBuilder",
    ),
    "GridPlotter": ("gridalyn.interfaces.viz.interactive", "GridPlotter"),
    "BatteryAsset": ("gridalyn.assets", "BatteryAsset"),
    "get_dataset_path": ("gridalyn.foundation.data", "get_dataset_path"),
    "list_available_datasets": ("gridalyn.foundation.data", "list_available_datasets"),
    "LightSimPowerflowAdapter": ("gridalyn.simulation", "LightSimPowerflowAdapter"),
    "ReportMetadata": ("gridalyn.foundation", "ReportMetadata"),
    "aggregate_load_multipliers": (
        "gridalyn.assets.datagen",
        "aggregate_load_multipliers",
    ),
    "generate_residential_load_profiles": (
        "gridalyn.assets.datagen",
        "generate_residential_load_profiles",
    ),
    "scale_profiles_to_peaks": ("gridalyn.assets.datagen", "scale_profiles_to_peaks"),
    "init_project": ("gridalyn.projects.api", "init_project"),
    "load_der_dispatch_assets": (
        "gridalyn.projects.model_inputs",
        "load_der_dispatch_assets",
    ),
    "load_generated_bus_loads_mw": (
        "gridalyn.projects.model_inputs",
        "load_generated_bus_loads_mw",
    ),
    "load_generated_load_multipliers": (
        "gridalyn.projects.model_inputs",
        "load_generated_load_multipliers",
    ),
    "load_generated_load_profiles": (
        "gridalyn.projects.model_inputs",
        "load_generated_load_profiles",
    ),
    "load_numeric_profile_array": (
        "gridalyn.projects.model_inputs",
        "load_numeric_profile_array",
    ),
    "load_project": ("gridalyn.projects.api", "load_project"),
    "load_prosumer_assets": ("gridalyn.projects.model_inputs", "load_prosumer_assets"),
    "load_radial_feeder_spec": (
        "gridalyn.projects.model_inputs",
        "load_radial_feeder_spec",
    ),
    "load_voltage_control_der_spec": (
        "gridalyn.projects.model_inputs",
        "load_voltage_control_der_spec",
    ),
    "plan_project": ("gridalyn.projects.api", "plan_project"),
    "RadialFeederSpec": ("gridalyn.assets", "RadialFeederSpec"),
    "project_input": ("gridalyn.projects.model_inputs", "project_input"),
    "project_regression": ("gridalyn.projects.api", "project_regression"),
    "project_script": ("gridalyn.projects.scripting", "project_script"),
    "project_sense_check": ("gridalyn.projects.api", "project_sense_check"),
    "project_status": ("gridalyn.projects.api", "project_status"),
    "project_verify": ("gridalyn.projects.api", "project_verify"),
    "run_workflow": ("gridalyn.projects.api", "run_workflow"),
    "write_report": ("gridalyn.foundation", "write_report"),
    "VoltageControlDERSpec": ("gridalyn.assets", "VoltageControlDERSpec"),
    "VoltageControlEnvironment": ("gridalyn.simulation", "VoltageControlEnvironment"),
    "VoltageControlEnvironmentSpec": (
        "gridalyn.simulation",
        "VoltageControlEnvironmentSpec",
    ),
    "validate_project": ("gridalyn.projects.api", "validate_project"),
    "build_operation_run": ("gridalyn.operations", "build_operation_run"),
    "build_radial_pandapower_feeder": (
        "gridalyn.simulation",
        "build_radial_pandapower_feeder",
    ),
    "build_synthetic_network_from_geojson": (
        "gridalyn.simulation.simulators.powerflow.synthetic_network",
        "build_synthetic_network_from_geojson",
    ),
    "build_voltage_control_feeder": (
        "gridalyn.simulation",
        "build_voltage_control_feeder",
    ),
    "SyntheticNetworkBuildResult": (
        "gridalyn.simulation.simulators.powerflow.synthetic_network",
        "SyntheticNetworkBuildResult",
    ),
    "build_ieee33_benchmark_feeder": (
        "gridalyn.simulation",
        "build_ieee33_benchmark_feeder",
    ),
    "validate_operation_run": ("gridalyn.operations", "validate_operation_run"),
    "write_powerflow_report": ("gridalyn.simulation", "write_powerflow_report"),
    "write_voltage_profile_figure": (
        "gridalyn.simulation",
        "write_voltage_profile_figure",
    ),
}


def __getattr__(name: str):
    if name in _LAZY_EXPORTS:
        module_name, attr_name = _LAZY_EXPORTS[name]
        module = import_module(module_name)
        value = (
            module
            if attr_name == name and module_name.endswith(f".{name}")
            else getattr(module, attr_name)
        )
        globals()[name] = value
        return value
    raise AttributeError(f"module 'gridalyn' has no attribute {name!r}")


def __dir__() -> list[str]:
    """List the module namespace plus every lazily exported public name.

    Returns:
        Sorted names, so ``dir()`` and :func:`inspect.getmembers` see the
        lazy exports that ``__getattr__`` resolves on demand.
    """
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
