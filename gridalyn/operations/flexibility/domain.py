"""Deprecated shim for the moved flexibility domain contracts.

The canonical home is :mod:`gridalyn.operations.domain`. This module remains
importable so half-migrated consumers keep resolving to the IDENTICAL object;
it emits a quiet :class:`DeprecationWarning` and re-exports from the new home.
"""

from __future__ import annotations

import warnings
from importlib import import_module

_CANONICAL = "gridalyn.operations.domain"
_MOVED = {
    "AggregatorPortfolio",
    "FlexibilityOffer",
    "DispatchInstruction",
    "SettlementRecord",
    "build_aggregator_portfolios",
    "build_provider_offers",
    "build_dispatch_instructions",
    "build_settlement_records",
}


def __getattr__(name: str) -> object:
    """Resolve a moved domain symbol from its canonical home.

    Args:
        name: Public attribute requested on the legacy module path.

    Returns:
        The identical object now living in :mod:`gridalyn.operations.domain`.

    Raises:
        AttributeError: If ``name`` is not a moved domain symbol.
    """
    if name in _MOVED:
        warnings.warn(
            f"import {name} from {_CANONICAL} "
            f"(gridalyn.operations.flexibility.domain is deprecated)",
            DeprecationWarning,
            stacklevel=2,
        )
        return getattr(import_module(_CANONICAL), name)
    raise AttributeError(
        f"module 'gridalyn.operations.flexibility.domain' has no attribute {name!r}"
    )
