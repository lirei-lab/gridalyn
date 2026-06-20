"""Deprecated shim: NetworkConstraintModel moved to canonical home.

The ``NetworkConstraintModel`` Protocol now lives in the canonical
:mod:`gridalyn.operations.constraints` surface (D-02). This module is kept
importable as a quiet :class:`DeprecationWarning` shim resolving to the IDENTICAL
canonical object (CLEAN-02). Import from the canonical home instead.
"""

from __future__ import annotations

import warnings
from importlib import import_module

_CANONICAL = "gridalyn.operations.constraints"
_EXPORTS = {"NetworkConstraintModel"}


def __getattr__(name: str) -> object:
    """Resolve the moved NetworkConstraintModel from its canonical home."""
    if name in _EXPORTS:
        warnings.warn(
            f"import {name} from {_CANONICAL} "
            f"(gridalyn.operations.market.network_constraints.{name} is deprecated)",
            DeprecationWarning,
            stacklevel=2,
        )
        value = getattr(import_module(_CANONICAL), name)
        globals()[name] = value
        return value
    raise AttributeError(
        f"module 'gridalyn.operations.market.network_constraints' has no attribute {name!r}"
    )
