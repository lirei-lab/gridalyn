"""Deprecated shim: settlement moved to gridalyn.operations.settlement.

``AggregatorSettlementReceipt`` and ``calculate_period_settlement`` (the §4
baseline source) now live in :mod:`gridalyn.operations.settlement`. This module
is kept importable as a quiet :class:`DeprecationWarning` shim resolving to the
IDENTICAL canonical object (CLEAN-01). Import from the canonical home instead.
"""

from __future__ import annotations

import warnings
from importlib import import_module

_CANONICAL = "gridalyn.operations.settlement"
_EXPORTS = {"AggregatorSettlementReceipt", "calculate_period_settlement"}


def __getattr__(name: str) -> object:
    """Resolve a moved settlement symbol from gridalyn.operations.settlement."""
    if name in _EXPORTS:
        warnings.warn(
            f"import {name} from {_CANONICAL} "
            f"(gridalyn.operations.market.settlement.{name} is deprecated)",
            DeprecationWarning,
            stacklevel=2,
        )
        value = getattr(import_module(_CANONICAL), name)
        globals()[name] = value
        return value
    raise AttributeError(
        f"module 'gridalyn.operations.market.settlement' has no attribute {name!r}"
    )
