"""Deprecated location of the network observation contract.

The contract moved down to :mod:`gridalyn.twin.observation` in Phase 11: "what
a solved network shows" is a property of the network, not of the solver, and
``twin`` sits below ``simulation``. This package remains so that the public
import surface shipped on 2026-08-11 keeps resolving.

**It re-exports, it does not redefine.** Every name below is the object
:mod:`gridalyn.twin.observation.contract` defines, so
``gridalyn.simulation.observation.NetworkObservation is
gridalyn.twin.observation.contract.NetworkObservation`` holds. A shim that
built a second class would give two types with one name -- the
``NetworkModel``/``NetworkSnapshot`` split Phase 11 exists to end.

The :class:`DeprecationWarning` is emitted here rather than in the sibling
``contract`` module because Python imports a package before any of its
submodules, so this runs exactly once for either import path -- ``import
gridalyn.simulation.observation`` and ``import
gridalyn.simulation.observation.contract`` alike -- instead of warning twice
for the deeper one.

Imports here are eager, unlike the ``_LAZY_EXPORTS`` map this package used to
carry. A deprecation shim has to execute to warn, and what it re-exports
reaches only pandas and numpy, both base dependencies; the laziness that
matters now lives in :mod:`gridalyn.twin.observation`.
"""

from __future__ import annotations

import warnings

from gridalyn.twin.observation.contract import (
    AS_OF_ABSENT_REASON,
    BUS_VOLTAGE_COLUMN,
    LINE_LOADING_COLUMN,
    LINE_LOSS_COLUMN,
    NetworkObservation,
    observe_network,
)

#: Emitted on import of this package or of its ``contract`` submodule.
DEPRECATION_MESSAGE = (
    "gridalyn.simulation.observation moved to gridalyn.twin.observation in "
    "Phase 11, because observed state belongs to the layer that owns the "
    "network rather than to the solver; this shim re-exports the same objects "
    "and will be removed in a future release -- import from "
    "gridalyn.twin.observation.contract instead"
)

warnings.warn(DEPRECATION_MESSAGE, DeprecationWarning, stacklevel=2)

__all__ = [
    "AS_OF_ABSENT_REASON",
    "BUS_VOLTAGE_COLUMN",
    "DEPRECATION_MESSAGE",
    "LINE_LOADING_COLUMN",
    "LINE_LOSS_COLUMN",
    "NetworkObservation",
    "observe_network",
]
