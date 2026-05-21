"""User and system interface facade for CLI, reports, dashboard, and graphs."""

from __future__ import annotations

from importlib import import_module

_LAZY_EXPORTS = {
    "GridPlotter": ("gridalyn.interfaces.viz.interactive", "GridPlotter"),
    "build_dashboard_catalog": ("gridalyn.interfaces.reporting", "build_dashboard_catalog"),
    "build_digital_twin_reports": ("gridalyn.interfaces.reporting", "build_digital_twin_reports"),
    "canonical_report": ("gridalyn.interfaces.reporting", "canonical_report"),
    "dashboard_main": ("gridalyn.interfaces.cli.dashboard", "main"),
    "digital_twin_main": ("gridalyn.interfaces.cli.digital_twin", "main"),
    "flexibility_main": ("gridalyn.interfaces.cli.flexibility", "main"),
    "gridalyn_main": ("gridalyn.interfaces.cli.gridalyn", "main"),
    "platform_main": ("gridalyn.interfaces.cli.platform", "main"),
    "project_main": ("gridalyn.interfaces.cli.project", "main"),
    "semantic_main": ("gridalyn.interfaces.cli.semantic", "main"),
    "write_dashboard_catalog": ("gridalyn.interfaces.reporting", "write_dashboard_catalog"),
    "write_json": ("gridalyn.interfaces.reporting", "write_json"),
    "write_report": ("gridalyn.interfaces.reporting", "write_report"),
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str):
    if name in _LAZY_EXPORTS:
        module_name, attr_name = _LAZY_EXPORTS[name]
        value = getattr(import_module(module_name), attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'gridalyn.interfaces' has no attribute {name!r}")
