"""Deprecated shim: prosumer realtime market moved to canonical home.

The prosumer real-time market runner now lives in the canonical
:mod:`gridalyn.operations.prosumer_realtime` surface (D-01). This module is kept
importable as a quiet :class:`DeprecationWarning` shim resolving to the IDENTICAL
canonical objects (CLEAN-02). Import from the canonical home instead.
"""

from __future__ import annotations

import warnings
from importlib import import_module

_CANONICAL = "gridalyn.operations.prosumer_realtime"
_EXPORTS = {
    "ProsumerRealtimeMarketConfig",
    "ProsumerRealtimeMarketResult",
    "build_interval_forecast",
    "build_prosumer_realtime_market_summary",
    "clear_prosumer_interval",
    "run_prosumer_powerflow",
    "run_prosumer_realtime_market",
    "write_prosumer_market_dispatch_figure",
}


def __getattr__(name: str) -> object:
    """Resolve a moved prosumer symbol from its canonical home."""
    if name in _EXPORTS:
        warnings.warn(
            f"import {name} from {_CANONICAL} "
            f"(gridalyn.operations.market.prosumer_realtime.{name} is deprecated)",
            DeprecationWarning,
            stacklevel=2,
        )
        value = getattr(import_module(_CANONICAL), name)
        globals()[name] = value
        return value
    raise AttributeError(
        f"module 'gridalyn.operations.market.prosumer_realtime' has no attribute {name!r}"
    )
