"""Reusable simulation environments for optimization and control projects."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "VoltageControlEnvironment": (
        "gridalyn.simulation.environments.voltage_control",
        "VoltageControlEnvironment",
    ),
    "VoltageControlEnvironmentSpec": (
        "gridalyn.simulation.environments.voltage_control",
        "VoltageControlEnvironmentSpec",
    ),
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    """Lazily resolve an environment symbol from its implementation module.

    Args:
        name: Public attribute requested on ``gridalyn.simulation.environments``.

    Returns:
        The resolved attribute, cached into module globals for free re-access.

    Raises:
        AttributeError: If ``name`` is not a known environment symbol.
    """
    if name in _LAZY_EXPORTS:
        module_name, attr_name = _LAZY_EXPORTS[name]
        value = getattr(import_module(module_name), attr_name)
        globals()[name] = value
        return value
    raise AttributeError(
        f"module 'gridalyn.simulation.environments' has no attribute {name!r}"
    )
