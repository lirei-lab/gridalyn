"""Graph/database adapters.

Only :class:`FederatedGraphAdapter` is part of the current platform path. The
old embedded Falkor/DuckDB manager is still importable for archived demos, but
it is intentionally hidden from ``__all__`` and emits a deprecation warning.
"""

from __future__ import annotations

import warnings

from gridalyn.twin.db.federated_graph_adapter import FederatedGraphAdapter

__all__ = [
    "FederatedGraphAdapter",
]

_LEGACY_DB_EXPORTS = {
    "DigitalTwinManager": ("gridalyn.twin.db.manager", "DigitalTwinManager"),
    "FalkorAdapter": ("gridalyn.twin.db.falkor_adapter", "FalkorAdapter"),
    "DuckAdapter": ("gridalyn.twin.db.duck_adapter", "DuckAdapter"),
    "DashboardExporter": ("gridalyn.twin.db.dashboard_sync", "DashboardExporter"),
}


def __getattr__(name: str):
    if name in _LEGACY_DB_EXPORTS:
        warnings.warn(
            f"gridalyn.twin.db.{name} is legacy. Use instances/default/digital_twin/* artifacts and "
            "gridalyn.twin.db.FederatedGraphAdapter for current graph workflows.",
            DeprecationWarning,
            stacklevel=2,
        )
        module_name, attr_name = _LEGACY_DB_EXPORTS[name]
        import importlib

        module = importlib.import_module(module_name)
        return getattr(module, attr_name)
    raise AttributeError(f"module 'gridalyn.twin.db' has no attribute {name!r}")
