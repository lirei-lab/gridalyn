"""Deprecated shim: locational verification moved to operations.verification.

``apply_locational_selections``, ``build_locational_clearing_verification_report``
and ``write_locational_verification_outputs`` now live in the canonical
:mod:`gridalyn.operations.verification` surface. This module is kept importable as
a quiet :class:`DeprecationWarning` shim resolving to the IDENTICAL canonical
object (CLEAN-01). Import from the canonical home instead.
"""

from __future__ import annotations

import warnings
from importlib import import_module

_CANONICAL = "gridalyn.operations.verification"
_EXPORTS = {
    "apply_locational_selections",
    "build_locational_clearing_verification_report",
    "write_locational_verification_outputs",
}


def __getattr__(name: str) -> object:
    """Resolve a moved verification symbol from operations.verification."""
    if name in _EXPORTS:
        warnings.warn(
            f"import {name} from {_CANONICAL} "
            f"(gridalyn.operations.market.locational_verification.{name} "
            f"is deprecated)",
            DeprecationWarning,
            stacklevel=2,
        )
        value = getattr(import_module(_CANONICAL), name)
        globals()[name] = value
        return value
    raise AttributeError(
        f"module 'gridalyn.operations.market.locational_verification' has no "
        f"attribute {name!r}"
    )
