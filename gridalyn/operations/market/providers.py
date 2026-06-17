"""Deprecated shim: provider registry/sensitivity moved to clearing.selection.

The provider registry and network-sensitivity helpers now live in
:mod:`gridalyn.operations.clearing.selection`. This module is kept importable as
a quiet :class:`DeprecationWarning` shim resolving to the IDENTICAL canonical
object (CLEAN-01). Import from the canonical home instead.
"""

from __future__ import annotations

import warnings
from importlib import import_module

_CANONICAL = "gridalyn.operations.clearing.selection"
_EXPORTS = {
    "build_network_sensitivity",
    "build_provider_registry",
    "select_providers_for_constraint",
    "summarize_provider_registry",
}


def __getattr__(name: str) -> object:
    """Resolve a moved provider-registry symbol from clearing.selection."""
    if name in _EXPORTS:
        warnings.warn(
            f"import {name} from {_CANONICAL} "
            f"(gridalyn.operations.market.providers.{name} is deprecated)",
            DeprecationWarning,
            stacklevel=2,
        )
        value = getattr(import_module(_CANONICAL), name)
        globals()[name] = value
        return value
    raise AttributeError(
        f"module 'gridalyn.operations.market.providers' has no attribute {name!r}"
    )
