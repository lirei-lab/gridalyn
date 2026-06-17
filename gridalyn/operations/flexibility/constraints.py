"""Deprecated shim for the moved flexibility network-constraint contracts.

The canonical home is :mod:`gridalyn.operations.constraints`. This module
remains importable so half-migrated consumers keep resolving to the IDENTICAL
object; it emits a quiet :class:`DeprecationWarning` and re-exports from the
new home.
"""

from __future__ import annotations

import warnings
from importlib import import_module

_CANONICAL = "gridalyn.operations.constraints"
_MOVED = {
    "NetworkConstraint",
    "build_network_constraint_set",
    "summarize_network_constraints",
}


def __getattr__(name: str) -> object:
    """Resolve a moved network-constraint symbol from its canonical home.

    Args:
        name: Public attribute requested on the legacy module path.

    Returns:
        The identical object now in :mod:`gridalyn.operations.constraints`.

    Raises:
        AttributeError: If ``name`` is not a moved constraint symbol.
    """
    if name in _MOVED:
        warnings.warn(
            f"import {name} from {_CANONICAL} "
            f"(gridalyn.operations.flexibility.constraints is deprecated)",
            DeprecationWarning,
            stacklevel=2,
        )
        return getattr(import_module(_CANONICAL), name)
    raise AttributeError(
        f"module 'gridalyn.operations.flexibility.constraints' "
        f"has no attribute {name!r}"
    )
