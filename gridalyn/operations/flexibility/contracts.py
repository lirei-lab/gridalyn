"""Deprecated shim for the moved flexibility operation contracts.

The canonical home is :mod:`gridalyn.operations.contracts`. This module remains
importable so half-migrated consumers keep resolving to the IDENTICAL object;
it emits a quiet :class:`DeprecationWarning` and re-exports from the new home.
"""

from __future__ import annotations

import warnings
from importlib import import_module

_CANONICAL = "gridalyn.operations.contracts"
_MOVED = {
    "FlexibilityOperationContext",
    "FlexibilityOperationValidation",
    "build_operation_context",
    "validate_flexibility_operation_inputs",
    "OPERATION_SCHEMA_VERSION",
    "PROVIDER_COLUMNS",
    "REQUIREMENT_COLUMNS",
    "SURROGATE_IMPACT_COLUMNS",
    "TOPOLOGY_IMPACT_COLUMNS",
}


def __getattr__(name: str) -> object:
    """Resolve a moved contract symbol from its canonical home.

    Args:
        name: Public attribute requested on the legacy module path.

    Returns:
        The identical object now living in :mod:`gridalyn.operations.contracts`.

    Raises:
        AttributeError: If ``name`` is not a moved contract symbol.
    """
    if name in _MOVED:
        warnings.warn(
            f"import {name} from {_CANONICAL} "
            f"(gridalyn.operations.flexibility.contracts is deprecated)",
            DeprecationWarning,
            stacklevel=2,
        )
        return getattr(import_module(_CANONICAL), name)
    raise AttributeError(
        f"module 'gridalyn.operations.flexibility.contracts' has no attribute {name!r}"
    )
