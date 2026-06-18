"""Deprecated shim: CLS replay moved to gridalyn.operations.replay.

``CLSMarketReplayContext``, ``prepare_cls_market_replay_context`` and
``summarize_stage2_realizations`` now live in the canonical
:mod:`gridalyn.operations.replay` surface (the shared-RNG draw sites were moved
verbatim). This module is kept importable as a quiet :class:`DeprecationWarning`
shim resolving to the IDENTICAL canonical object (CLEAN-01). Import from the
canonical home instead.
"""

from __future__ import annotations

import warnings
from importlib import import_module

_CANONICAL = "gridalyn.operations.replay"
_EXPORTS = {
    "CLSMarketReplayContext",
    "prepare_cls_market_replay_context",
    "summarize_stage2_realizations",
}


def __getattr__(name: str) -> object:
    """Resolve a moved replay symbol from gridalyn.operations.replay."""
    if name in _EXPORTS:
        warnings.warn(
            f"import {name} from {_CANONICAL} "
            f"(gridalyn.operations.flexibility.cls_replay.{name} is deprecated)",
            DeprecationWarning,
            stacklevel=2,
        )
        value = getattr(import_module(_CANONICAL), name)
        globals()[name] = value
        return value
    raise AttributeError(
        f"module 'gridalyn.operations.flexibility.cls_replay' has no attribute "
        f"{name!r}"
    )
