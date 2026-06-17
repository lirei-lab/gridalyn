"""Deprecated shim: locational clearing moved to clearing.selection.

The locational SELECTION core now lives in
:mod:`gridalyn.operations.clearing.selection`. This module is kept importable as
a quiet :class:`DeprecationWarning` shim resolving to the IDENTICAL canonical
object (CLEAN-01). Import from the canonical home instead.
"""

from __future__ import annotations

import warnings
from importlib import import_module

_CANONICAL = "gridalyn.operations.clearing.selection"
_EXPORTS = {
    "build_constraint_requirements",
    "build_locational_clearing",
    "write_locational_clearing_outputs",
}


def __getattr__(name: str) -> object:
    """Resolve a moved locational-clearing symbol from clearing.selection."""
    if name in _EXPORTS:
        warnings.warn(
            f"import {name} from {_CANONICAL} "
            f"(gridalyn.operations.market.locational_clearing.{name} is "
            "deprecated)",
            DeprecationWarning,
            stacklevel=2,
        )
        value = getattr(import_module(_CANONICAL), name)
        globals()[name] = value
        return value
    raise AttributeError(
        f"module 'gridalyn.operations.market.locational_clearing' has no "
        f"attribute {name!r}"
    )
