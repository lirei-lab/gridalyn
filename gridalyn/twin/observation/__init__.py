"""Observed network state: one definition of what a solved network shows.

The contract lives here, in the layer that owns network state, rather than in
``gridalyn.simulation`` where Phase 10 first needed it. Only the *producer* of
a solved operating point belongs to the simulation layer; what that state shows
is a property of the network. ``gridalyn.simulation.observation`` re-exports
these objects behind a :class:`DeprecationWarning` and yields the identical
classes, not copies.

The map below is not stylistic. :mod:`gridalyn.twin.observation.contract`
imports pandas, a base dependency, so it does not leak today. The package
exists to be extended with observers for producers that *do* reach an optional
dependency -- ``lightsim2grid`` through ``pandapower``, or a surrogate.
Resolving eagerly would make the first such addition leak an optional
dependency out of ``import gridalyn.twin.observation``, which
``tests/test_import_hygiene.py`` fails on. That sweep is what proves the
package clean rather than assumes it.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "AS_OF_ABSENT_REASON": (
        "gridalyn.twin.observation.contract",
        "AS_OF_ABSENT_REASON",
    ),
    "BUS_VOLTAGE_COLUMN": (
        "gridalyn.twin.observation.contract",
        "BUS_VOLTAGE_COLUMN",
    ),
    "EntityJoin": (
        "gridalyn.twin.observation.ingest",
        "EntityJoin",
    ),
    "LINE_LOADING_COLUMN": (
        "gridalyn.twin.observation.contract",
        "LINE_LOADING_COLUMN",
    ),
    "LINE_LOSS_COLUMN": (
        "gridalyn.twin.observation.contract",
        "LINE_LOSS_COLUMN",
    ),
    "MEASUREMENT_COLUMNS": (
        "gridalyn.twin.observation.ingest",
        "MEASUREMENT_COLUMNS",
    ),
    "NetworkObservation": (
        "gridalyn.twin.observation.contract",
        "NetworkObservation",
    ),
    "ObservationProducerDescriptor": (
        "gridalyn.twin.observation.registry",
        "ObservationProducerDescriptor",
    ),
    "ObservationProducerRegistry": (
        "gridalyn.twin.observation.registry",
        "ObservationProducerRegistry",
    ),
    "ObservationProvenance": (
        "gridalyn.twin.observation.contract",
        "ObservationProvenance",
    ),
    "SUPPORTED_QUANTITIES": (
        "gridalyn.twin.observation.ingest",
        "SUPPORTED_QUANTITIES",
    ),
    "UnknownObservationProducerError": (
        "gridalyn.twin.observation.registry",
        "UnknownObservationProducerError",
    ),
    "default_observation_producer_registry": (
        "gridalyn.twin.observation.registry",
        "default_observation_producer_registry",
    ),
    "load_measurements": (
        "gridalyn.twin.observation.ingest",
        "load_measurements",
    ),
    "observe_network": (
        "gridalyn.twin.observation.contract",
        "observe_network",
    ),
    "read_measured_observations": (
        "gridalyn.twin.observation.ingest",
        "read_measured_observations",
    ),
    "register_observation_producer_extension": (
        "gridalyn.twin.observation.registry",
        "register_observation_producer_extension",
    ),
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    """Lazily resolve an observation symbol from its implementation module.

    Args:
        name: Public attribute requested on ``gridalyn.twin.observation``.

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
        f"module 'gridalyn.twin.observation' has no attribute {name!r}"
    )


def __dir__() -> list[str]:
    """List the module namespace plus every lazily exported public name.

    Returns:
        Sorted names, so ``dir()`` and :func:`inspect.getmembers` see the
        lazy exports that ``__getattr__`` resolves on demand.
    """
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
