"""Simulation, powerflow, network-impact, and validation facade."""

from __future__ import annotations

from importlib import import_module

_LAZY_EXPORTS = {
    "MonteCarloSimulationManager": (
        "gridalyn.simulation.simulators.powerflow.runner",
        "MonteCarloSimulationManager",
    ),
    "PandapowerGridBuilder": (
        "gridalyn.simulation.simulators.powerflow.builder",
        "PandapowerGridBuilder",
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
    "fit_physics_surrogate": ("gridalyn.simulation.analytics.network_impact", "fit_physics_surrogate"),
    "predict_physics_impact": ("gridalyn.simulation.analytics.network_impact", "predict_physics_impact"),
    "write_network_impact_catalog": (
        "gridalyn.simulation.analytics.network_impact",
        "write_network_impact_catalog",
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
