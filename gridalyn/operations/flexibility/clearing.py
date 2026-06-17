"""Deprecated shim: flexibility clearing facade moved to clearing.selection.

The frozen ``run_flexibility_clearing_operation`` entry point now lives in
:mod:`gridalyn.operations.clearing.selection`. This module is kept importable as
a quiet :class:`DeprecationWarning` shim resolving to the IDENTICAL canonical
object (CLEAN-01). Import from the canonical home instead.
"""

from __future__ import annotations

import warnings
from importlib import import_module

_CANONICAL = "gridalyn.operations.clearing.selection"
_EXPORTS = {"run_flexibility_clearing_operation"}


def __getattr__(name: str) -> object:
    """Resolve the moved clearing entry from clearing.selection."""
    if name in _EXPORTS:
        warnings.warn(
            f"import {name} from {_CANONICAL} "
            f"(gridalyn.operations.flexibility.clearing.{name} is deprecated)",
            DeprecationWarning,
            stacklevel=2,
        )
        value = getattr(import_module(_CANONICAL), name)
        globals()[name] = value
        return value
    raise AttributeError(
        f"module 'gridalyn.operations.flexibility.clearing' has no attribute "
        f"{name!r}"
    )
