"""Deprecated shim: scorecard moved to gridalyn.operations.settlement.

``build_flexibility_clearing_scorecard`` and
``write_flexibility_clearing_scorecard`` now live in the canonical
:mod:`gridalyn.operations.settlement` surface (VERIF-01). This module is kept
importable as a quiet :class:`DeprecationWarning` shim resolving to the IDENTICAL
canonical object (CLEAN-01). Import from the canonical home instead.
"""

from __future__ import annotations

import warnings
from importlib import import_module

_CANONICAL = "gridalyn.operations.settlement"
_EXPORTS = {
    "POLICY_LABELS",
    "build_flexibility_clearing_scorecard",
    "write_flexibility_clearing_scorecard",
}


def __getattr__(name: str) -> object:
    """Resolve a moved scorecard symbol from gridalyn.operations.settlement."""
    if name in _EXPORTS:
        warnings.warn(
            f"import {name} from {_CANONICAL} "
            f"(gridalyn.operations.market.scorecard.{name} is deprecated)",
            DeprecationWarning,
            stacklevel=2,
        )
        value = getattr(import_module(_CANONICAL), name)
        globals()[name] = value
        return value
    raise AttributeError(
        f"module 'gridalyn.operations.market.scorecard' has no attribute {name!r}"
    )
