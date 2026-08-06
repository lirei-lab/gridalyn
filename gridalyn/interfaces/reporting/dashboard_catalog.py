"""Deprecated import path for the relocated dashboard-catalog helpers.

The implementation moved to :mod:`gridalyn.projects.dashboard_catalog`
(Plan 05-04, ledger #13). Only the two facade names were contractual in-repo,
but the deep path is externally visible for a published SDK, so this shim keeps
it importable (ledger #36) while warning callers to migrate. It re-exports and
writes nothing itself.
"""

from __future__ import annotations

import warnings

from gridalyn.projects.dashboard_catalog import (
    build_dashboard_catalog,
    write_dashboard_catalog,
)

__all__ = ["build_dashboard_catalog", "write_dashboard_catalog"]

warnings.warn(
    "gridalyn.interfaces.reporting.dashboard_catalog is deprecated; import "
    "build_dashboard_catalog and write_dashboard_catalog from "
    "gridalyn.projects.dashboard_catalog (or the gridalyn.interfaces.reporting "
    "facade) instead",
    DeprecationWarning,
    stacklevel=2,
)
