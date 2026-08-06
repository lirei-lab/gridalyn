"""Canonical report builders and JSON report helpers."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "artifact_references": (
        "gridalyn.interfaces.reporting.schemas",
        "artifact_references",
    ),
    "build_dashboard_catalog": (
        "gridalyn.projects.dashboard_catalog",
        "build_dashboard_catalog",
    ),
    "build_digital_twin_reports": (
        "gridalyn.interfaces.reporting.digital_twin",
        "build_digital_twin_reports",
    ),
    "canonical_report": (
        "gridalyn.interfaces.reporting.schemas",
        "canonical_report",
    ),
    "dispatch_timeseries_metrics": (
        "gridalyn.interfaces.reporting.metrics",
        "dispatch_timeseries_metrics",
    ),
    "load_json": ("gridalyn.interfaces.reporting.schemas", "load_json"),
    "now_iso": ("gridalyn.interfaces.reporting.schemas", "now_iso"),
    "relpath": ("gridalyn.interfaces.reporting.schemas", "relpath"),
    "report_input": ("gridalyn.interfaces.reporting.schemas", "report_input"),
    "sha256_file": ("gridalyn.interfaces.reporting.schemas", "sha256_file"),
    "write_dashboard_catalog": (
        "gridalyn.projects.dashboard_catalog",
        "write_dashboard_catalog",
    ),
    "write_json": ("gridalyn.interfaces.reporting.schemas", "write_json"),
    "write_report": ("gridalyn.interfaces.reporting.schemas", "write_report"),
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    """Lazily resolve a reporting symbol from its implementation module.

    Args:
        name: Public attribute requested on ``gridalyn.interfaces.reporting``.

    Returns:
        The resolved attribute, cached into module globals for free re-access.

    Raises:
        AttributeError: If ``name`` is not a known reporting symbol.
    """
    if name in _LAZY_EXPORTS:
        module_name, attr_name = _LAZY_EXPORTS[name]
        value = getattr(import_module(module_name), attr_name)
        globals()[name] = value
        return value
    raise AttributeError(
        f"module 'gridalyn.interfaces.reporting' has no attribute {name!r}"
    )


def __dir__() -> list[str]:
    """Return the public names, so introspection sees the lazy exports.

    Returns:
        The sorted public export names plus the module globals.
    """
    return sorted(set(__all__) | set(globals()))
