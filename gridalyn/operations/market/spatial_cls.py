"""Deprecated shim: spatial allocation moved to clearing.allocation.

The spatial ALLOCATION core now lives in
:mod:`gridalyn.operations.clearing.allocation`. This module is kept importable
as a quiet :class:`DeprecationWarning` shim resolving to the IDENTICAL canonical
object (CLEAN-01). Import from the canonical home instead.
"""

from __future__ import annotations

import warnings
from importlib import import_module

_CANONICAL = "gridalyn.operations.clearing.allocation"
_EXPORTS = {
    "SpatialClsResult",
    "allocate_addition_by_headroom",
    "allocate_reduction",
    "apply_spatial_cls",
}


def __getattr__(name: str) -> object:
    """Resolve a moved spatial-allocation symbol from clearing.allocation."""
    if name in _EXPORTS:
        warnings.warn(
            f"import {name} from {_CANONICAL} "
            f"(gridalyn.operations.market.spatial_cls.{name} is deprecated)",
            DeprecationWarning,
            stacklevel=2,
        )
        value = getattr(import_module(_CANONICAL), name)
        globals()[name] = value
        return value
    raise AttributeError(
        f"module 'gridalyn.operations.market.spatial_cls' has no attribute {name!r}"
    )
