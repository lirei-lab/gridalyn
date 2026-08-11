"""Network observation: one definition of what a solved network shows.

The map below is not stylistic. :mod:`gridalyn.simulation.observation.contract`
imports pandas, and this package exists to be extended with observers for
producers that do reach an optional dependency -- ``lightsim2grid`` through
``pandapower``, or a surrogate. Resolving eagerly would make the first such
addition leak an optional dependency out of ``import gridalyn.simulation.
observation``, which ``tests/test_import_hygiene.py`` fails on. The contract
itself reaches only base dependencies today, and that sweep is what proves it
rather than assumes it.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "BUS_VOLTAGE_COLUMN": (
        "gridalyn.simulation.observation.contract",
        "BUS_VOLTAGE_COLUMN",
    ),
    "LINE_LOADING_COLUMN": (
        "gridalyn.simulation.observation.contract",
        "LINE_LOADING_COLUMN",
    ),
    "LINE_LOSS_COLUMN": (
        "gridalyn.simulation.observation.contract",
        "LINE_LOSS_COLUMN",
    ),
    "NetworkObservation": (
        "gridalyn.simulation.observation.contract",
        "NetworkObservation",
    ),
    "observe_network": (
        "gridalyn.simulation.observation.contract",
        "observe_network",
    ),
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    """Lazily resolve an observation symbol from its implementation module.

    Args:
        name: Public attribute requested on ``gridalyn.simulation.observation``.

    Returns:
        The resolved attribute, cached into module globals for free re-access.

    Raises:
        AttributeError: If ``name`` is not a known observation symbol.
    """
    if name in _LAZY_EXPORTS:
        module_name, attr_name = _LAZY_EXPORTS[name]
        value = getattr(import_module(module_name), attr_name)
        globals()[name] = value
        return value
    raise AttributeError(
        f"module 'gridalyn.simulation.observation' has no attribute {name!r}"
    )


def __dir__() -> list[str]:
    """List the module namespace plus every lazily exported public name.

    Returns:
        Sorted names, so ``dir()`` and :func:`inspect.getmembers` see the
        lazy exports that ``__getattr__`` resolves on demand.
    """
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
