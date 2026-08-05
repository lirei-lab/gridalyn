"""Reusable control algorithms for Gridalyn simulation environments."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "TabularVoltageControlConfig": (
        "gridalyn.simulation.control.tabular_voltage",
        "TabularVoltageControlConfig",
    ),
    "TabularVoltageControlResult": (
        "gridalyn.simulation.control.tabular_voltage",
        "TabularVoltageControlResult",
    ),
    "summarize_tabular_voltage_control": (
        "gridalyn.simulation.control.tabular_voltage",
        "summarize_tabular_voltage_control",
    ),
    "train_tabular_voltage_controller": (
        "gridalyn.simulation.control.tabular_voltage",
        "train_tabular_voltage_controller",
    ),
    "write_tabular_voltage_control_figure": (
        "gridalyn.simulation.control.tabular_voltage",
        "write_tabular_voltage_control_figure",
    ),
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    """Lazily resolve a control symbol from its implementation module.

    Args:
        name: Public attribute requested on ``gridalyn.simulation.control``.

    Returns:
        The resolved attribute, cached into module globals for free re-access.

    Raises:
        AttributeError: If ``name`` is not a known control symbol.
    """
    if name in _LAZY_EXPORTS:
        module_name, attr_name = _LAZY_EXPORTS[name]
        value = getattr(import_module(module_name), attr_name)
        globals()[name] = value
        return value
    raise AttributeError(
        f"module 'gridalyn.simulation.control' has no attribute {name!r}"
    )
