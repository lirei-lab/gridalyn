"""Deprecated shim: market simulation engine moved to clearing.engine_mode.

``MarketSimulationEngine`` now lives in
:mod:`gridalyn.operations.clearing.engine_mode`. This module is kept importable
as a quiet :class:`DeprecationWarning` shim resolving to the IDENTICAL canonical
object (CLEAN-01). Import from the canonical home instead.
"""

from __future__ import annotations

import warnings
from importlib import import_module

_CANONICAL = "gridalyn.operations.clearing.engine_mode"
_EXPORTS = {"MarketSimulationEngine"}


def __getattr__(name: str) -> object:
    """Resolve a moved engine symbol from clearing.engine_mode."""
    if name in _EXPORTS:
        warnings.warn(
            f"import {name} from {_CANONICAL} "
            f"(gridalyn.operations.market.engine.{name} is deprecated)",
            DeprecationWarning,
            stacklevel=2,
        )
        value = getattr(import_module(_CANONICAL), name)
        globals()[name] = value
        return value
    raise AttributeError(
        f"module 'gridalyn.operations.market.engine' has no attribute {name!r}"
    )
