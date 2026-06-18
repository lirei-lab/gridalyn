"""Deprecated shim: shadow report moved to gridalyn.operations.verification.

``build_shadow_report`` and ``write_shadow_report`` now live in the canonical
:mod:`gridalyn.operations.verification` surface. This module is kept importable as
a quiet :class:`DeprecationWarning` shim resolving to the IDENTICAL canonical
object (CLEAN-01). Import from the canonical home instead.
"""

from __future__ import annotations

import warnings
from importlib import import_module

_CANONICAL = "gridalyn.operations.verification"
_EXPORTS = {"build_shadow_report", "write_shadow_report"}


def __getattr__(name: str) -> object:
    """Resolve a moved shadow-report symbol from operations.verification."""
    if name in _EXPORTS:
        warnings.warn(
            f"import {name} from {_CANONICAL} "
            f"(gridalyn.operations.market.provider_shadow.{name} is deprecated)",
            DeprecationWarning,
            stacklevel=2,
        )
        value = getattr(import_module(_CANONICAL), name)
        globals()[name] = value
        return value
    raise AttributeError(
        f"module 'gridalyn.operations.market.provider_shadow' has no attribute "
        f"{name!r}"
    )
