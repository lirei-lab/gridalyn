"""Surrogates: one contract, one registry, one stated error bound each.

The map below defers a real cost rather than a style preference: importing
:mod:`gridalyn.simulation.surrogates.registry` pulls the whole
``analytics.network_impact`` closure -- pandas plus
``gridalyn.twin.semantic.profile`` and its ``rdflib`` graph -- because that is
where the two shipped surrogates live. A consumer that only needs
:class:`~gridalyn.simulation.surrogates.contract.ErrorBound` should not pay for
it.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "DEFAULT_SURROGATE_ID": (
        "gridalyn.simulation.surrogates.registry",
        "DEFAULT_SURROGATE_ID",
    ),
    "ErrorBound": (
        "gridalyn.simulation.surrogates.contract",
        "ErrorBound",
    ),
    "Surrogate": (
        "gridalyn.simulation.surrogates.contract",
        "Surrogate",
    ),
    "SurrogateDescriptor": (
        "gridalyn.simulation.surrogates.contract",
        "SurrogateDescriptor",
    ),
    "SurrogateRegistry": (
        "gridalyn.simulation.surrogates.registry",
        "SurrogateRegistry",
    ),
    "UnboundedSurrogateError": (
        "gridalyn.simulation.surrogates.registry",
        "UnboundedSurrogateError",
    ),
    "UnknownSurrogateError": (
        "gridalyn.simulation.surrogates.registry",
        "UnknownSurrogateError",
    ),
    "default_surrogate_registry": (
        "gridalyn.simulation.surrogates.registry",
        "default_surrogate_registry",
    ),
    "describe_surrogate": (
        "gridalyn.simulation.surrogates.contract",
        "describe_surrogate",
    ),
    "measure_error_bound": (
        "gridalyn.simulation.surrogates.contract",
        "measure_error_bound",
    ),
    "measure_relief_error_bound": (
        "gridalyn.simulation.surrogates.contract",
        "measure_relief_error_bound",
    ),
    "register_surrogate_extension": (
        "gridalyn.simulation.surrogates.registry",
        "register_surrogate_extension",
    ),
    "registered_error_bounds": (
        "gridalyn.simulation.surrogates.registry",
        "registered_error_bounds",
    ),
    "resolve_surrogate": (
        "gridalyn.simulation.surrogates.registry",
        "resolve_surrogate",
    ),
    "unmeasured_error_bound": (
        "gridalyn.simulation.surrogates.contract",
        "unmeasured_error_bound",
    ),
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    """Lazily resolve a surrogate symbol from its implementation module.

    Args:
        name: Public attribute requested on ``gridalyn.simulation.surrogates``.

    Returns:
        The resolved attribute, cached into module globals for free re-access.

    Raises:
        AttributeError: If ``name`` is not a known surrogate symbol.
    """
    if name in _LAZY_EXPORTS:
        module_name, attr_name = _LAZY_EXPORTS[name]
        value = getattr(import_module(module_name), attr_name)
        globals()[name] = value
        return value
    raise AttributeError(
        f"module 'gridalyn.simulation.surrogates' has no attribute {name!r}"
    )


def __dir__() -> list[str]:
    """List the module namespace plus every lazily exported public name.

    Returns:
        Sorted names, so ``dir()`` and :func:`inspect.getmembers` see the
        lazy exports that ``__getattr__`` resolves on demand.
    """
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
