"""Deprecated shim: congestion forecast moved to gridalyn.operations.replay.

``CongestionForecastResult`` and ``build_congestion_forecast`` now live in the
canonical :mod:`gridalyn.operations.replay` surface. This module is kept
importable as a quiet :class:`DeprecationWarning` shim resolving to the IDENTICAL
canonical object (CLEAN-01). Import from the canonical home instead.
"""

from __future__ import annotations

import warnings
from importlib import import_module

_CANONICAL = "gridalyn.operations.replay"
_EXPORTS = {"CongestionForecastResult", "build_congestion_forecast"}


def __getattr__(name: str) -> object:
    """Resolve a moved congestion-forecast symbol from operations.replay."""
    if name in _EXPORTS:
        warnings.warn(
            f"import {name} from {_CANONICAL} "
            f"(gridalyn.operations.flexibility.thermal_screening.{name} "
            f"is deprecated)",
            DeprecationWarning,
            stacklevel=2,
        )
        value = getattr(import_module(_CANONICAL), name)
        globals()[name] = value
        return value
    raise AttributeError(
        f"module 'gridalyn.operations.flexibility.thermal_screening' has no "
        f"attribute {name!r}"
    )
