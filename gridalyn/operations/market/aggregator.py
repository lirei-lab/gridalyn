"""Deprecated shim: aggregator physical models moved to clearing.engine_mode.

The residential aggregator physical models (``FlexResource``,
``BlockFlexPortfolio``, ``BuildingAggregator``) and the
``generate_residential_portfolios`` factory now live in
:mod:`gridalyn.operations.clearing.engine_mode` (they are engine-path
collaborators, not the tabular ``domain.AggregatorPortfolio``). This module is
kept importable as a quiet :class:`DeprecationWarning` shim resolving to the
IDENTICAL canonical object (CLEAN-01). The DOM-04 relocation of generation to
``assets/datagen`` remains DEFERRED. Import from the canonical home instead.
"""

from __future__ import annotations

import warnings
from importlib import import_module

_CANONICAL = "gridalyn.operations.clearing.engine_mode"
_EXPORTS = {
    "FlexResource",
    "BlockFlexPortfolio",
    "BuildingAggregator",
    "generate_residential_portfolios",
}


def __getattr__(name: str) -> object:
    """Resolve a moved aggregator symbol from clearing.engine_mode."""
    if name in _EXPORTS:
        warnings.warn(
            f"import {name} from {_CANONICAL} "
            f"(gridalyn.operations.market.aggregator.{name} is deprecated)",
            DeprecationWarning,
            stacklevel=2,
        )
        value = getattr(import_module(_CANONICAL), name)
        globals()[name] = value
        return value
    raise AttributeError(
        f"module 'gridalyn.operations.market.aggregator' has no attribute {name!r}"
    )
