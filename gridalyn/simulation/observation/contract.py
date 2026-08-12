"""Deprecated path to the network observation contract.

The implementation moved to :mod:`gridalyn.twin.observation.contract` in
Phase 11. This module re-binds the same objects so that the deep import path
seven modules already use keeps resolving unchanged.

The :class:`DeprecationWarning` is emitted by this package's ``__init__``,
which Python necessarily executes before this submodule, so importing either
warns exactly once.
"""

from __future__ import annotations

from gridalyn.twin.observation.contract import (
    AS_OF_ABSENT_REASON,
    BUS_VOLTAGE_COLUMN,
    LINE_LOADING_COLUMN,
    LINE_LOSS_COLUMN,
    NetworkObservation,
    observe_network,
)

__all__ = [
    "AS_OF_ABSENT_REASON",
    "BUS_VOLTAGE_COLUMN",
    "LINE_LOADING_COLUMN",
    "LINE_LOSS_COLUMN",
    "NetworkObservation",
    "observe_network",
]
