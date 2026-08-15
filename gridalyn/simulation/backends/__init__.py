"""Power-flow backends: one contract, one registry, one place a solve happens.

The map below is required, not stylistic: :mod:`gridalyn.simulation.backends.
lightsim` reaches the truly-optional ``lightsim2grid`` module, and every
backend reaches ``pandapower`` (whose import puts ``lightsim2grid`` into
``sys.modules`` on its own). Resolving these eagerly would make
``import gridalyn.simulation.backends`` leak an optional dependency, which
``tests/test_import_hygiene.py`` fails on.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "DEFAULT_POWERFLOW_BACKEND_ID": (
        "gridalyn.simulation.backends.contract",
        "DEFAULT_POWERFLOW_BACKEND_ID",
    ),
    "LIGHTSIM2GRID_BACKEND_ID": (
        "gridalyn.simulation.backends.contract",
        "LIGHTSIM2GRID_BACKEND_ID",
    ),
    "LightSim2GridBackend": (
        "gridalyn.simulation.backends.lightsim",
        "LightSim2GridBackend",
    ),
    "PANDAPOWER_NATIVE_BACKEND_ID": (
        "gridalyn.simulation.backends.contract",
        "PANDAPOWER_NATIVE_BACKEND_ID",
    ),
    "PandapowerNativeBackend": (
        "gridalyn.simulation.backends.pandapower_native",
        "PandapowerNativeBackend",
    ),
    "PowerFlowBackend": (
        "gridalyn.simulation.backends.contract",
        "PowerFlowBackend",
    ),
    "PowerFlowBackendDescriptor": (
        "gridalyn.simulation.backends.contract",
        "PowerFlowBackendDescriptor",
    ),
    "PowerFlowBackendRegistry": (
        "gridalyn.simulation.backends.registry",
        "PowerFlowBackendRegistry",
    ),
    "UnknownPowerFlowBackendError": (
        "gridalyn.simulation.backends.registry",
        "UnknownPowerFlowBackendError",
    ),
    "default_powerflow_backend_registry": (
        "gridalyn.simulation.backends.registry",
        "default_powerflow_backend_registry",
    ),
    "describe_powerflow_backend": (
        "gridalyn.simulation.backends.contract",
        "describe_powerflow_backend",
    ),
    "register_powerflow_backend_extension": (
        "gridalyn.simulation.backends.registry",
        "register_powerflow_backend_extension",
    ),
    "resolve_powerflow_backend": (
        "gridalyn.simulation.backends.registry",
        "resolve_powerflow_backend",
    ),
    "solve_power_flow": (
        "gridalyn.simulation.backends.registry",
        "solve_power_flow",
    ),
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    """Lazily resolve a backend symbol from its implementation module.

    Args:
        name: Public attribute requested on ``gridalyn.simulation.backends``.

    Returns:
        The resolved attribute, cached into module globals for free re-access.

    Raises:
        AttributeError: If ``name`` is not a known backend symbol.
    """
    if name in _LAZY_EXPORTS:
        module_name, attr_name = _LAZY_EXPORTS[name]
        value = getattr(import_module(module_name), attr_name)
        globals()[name] = value
        return value
    raise AttributeError(
        f"module 'gridalyn.simulation.backends' has no attribute {name!r}"
    )


def __dir__() -> list[str]:
    """List the module namespace plus every lazily exported public name.

    Returns:
        Sorted names, so ``dir()`` and :func:`inspect.getmembers` see the
        lazy exports that ``__getattr__`` resolves on demand.
    """
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
