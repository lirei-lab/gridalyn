"""Deprecated shim: CLS market sweep moved to clearing.engine_mode.

``run_cls_capacity_allocation``, ``CLSCapacityAllocationResult``, and
``scenario_label`` now live in :mod:`gridalyn.operations.clearing.engine_mode`
(the two-stage Soft/Hard CLS authoring path). This module is kept importable as
a quiet :class:`DeprecationWarning` shim resolving to the IDENTICAL canonical
object (CLEAN-01). Import from the canonical home instead.
"""

from __future__ import annotations

import warnings
from importlib import import_module

_CANONICAL = "gridalyn.operations.clearing.engine_mode"
_EXPORTS = {
    "CLSCapacityAllocationResult",
    "run_cls_capacity_allocation",
    "scenario_label",
}


def __getattr__(name: str) -> object:
    """Resolve a moved CLS-market symbol from clearing.engine_mode."""
    if name in _EXPORTS:
        warnings.warn(
            f"import {name} from {_CANONICAL} "
            f"(gridalyn.operations.flexibility.cls_market.{name} is deprecated)",
            DeprecationWarning,
            stacklevel=2,
        )
        value = getattr(import_module(_CANONICAL), name)
        globals()[name] = value
        return value
    raise AttributeError(
        f"module 'gridalyn.operations.flexibility.cls_market' has no attribute "
        f"{name!r}"
    )
