"""Deprecated shim: artifacts moved to gridalyn.operations.artifacts.

``materialize_flexibility_operation_artifacts`` and its catalog/helper surface now
live in the canonical :mod:`gridalyn.operations.artifacts` module. This module is
kept importable as a quiet :class:`DeprecationWarning` shim resolving to the
IDENTICAL canonical object (CLEAN-01). Import from the canonical home instead.
"""

from __future__ import annotations

import warnings
from importlib import import_module

_CANONICAL = "gridalyn.operations.artifacts"
_EXPORTS = {
    "build_operations_catalog",
    "clearing_method_from_events",
    "infer_dt_h",
    "json_default",
    "materialize_flexibility_operation_artifacts",
    "model_version_id_from_artifacts",
    "relpath",
    "scenario_frame",
    "scenario_ids",
    "study_run_id_from_manifest",
    "webpath",
}


def __getattr__(name: str) -> object:
    """Resolve a moved artifact symbol from gridalyn.operations.artifacts."""
    if name in _EXPORTS:
        warnings.warn(
            f"import {name} from {_CANONICAL} "
            f"(gridalyn.operations.flexibility.artifacts.{name} is deprecated)",
            DeprecationWarning,
            stacklevel=2,
        )
        value = getattr(import_module(_CANONICAL), name)
        globals()[name] = value
        return value
    raise AttributeError(
        f"module 'gridalyn.operations.flexibility.artifacts' has no attribute "
        f"{name!r}"
    )
