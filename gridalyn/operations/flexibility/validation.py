"""Deprecated shim: validation moved to gridalyn.operations.verification.

``CLSOutputConsistencyResult`` and ``validate_cls_output_consistency`` now live in
the canonical :mod:`gridalyn.operations.verification` surface (VERIF-02). This
module is kept importable as a quiet :class:`DeprecationWarning` shim resolving to
the IDENTICAL canonical object (CLEAN-01). Import from the canonical home instead.
"""

from __future__ import annotations

import warnings
from importlib import import_module

_CANONICAL = "gridalyn.operations.verification"
_EXPORTS = {"CLSOutputConsistencyResult", "validate_cls_output_consistency"}


def __getattr__(name: str) -> object:
    """Resolve a moved validation symbol from gridalyn.operations.verification."""
    if name in _EXPORTS:
        warnings.warn(
            f"import {name} from {_CANONICAL} "
            f"(gridalyn.operations.flexibility.validation.{name} is deprecated)",
            DeprecationWarning,
            stacklevel=2,
        )
        value = getattr(import_module(_CANONICAL), name)
        globals()[name] = value
        return value
    raise AttributeError(
        f"module 'gridalyn.operations.flexibility.validation' has no attribute {name!r}"
    )
