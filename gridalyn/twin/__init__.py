"""Digital-twin model, topology, adapter, and semantic graph facade."""

from __future__ import annotations

from importlib import import_module

_LAZY_EXPORTS = {
    "CimParquetAdapter": ("gridalyn.twin.adapters", "CimParquetAdapter"),
    "ConnectedEquipment": ("gridalyn.twin.network", "ConnectedEquipment"),
    "DownstreamAssets": ("gridalyn.twin.network", "DownstreamAssets"),
    "NetworkAdapterDescriptor": ("gridalyn.twin.adapters", "NetworkAdapterDescriptor"),
    "NetworkAdapterRegistry": ("gridalyn.twin.adapters", "NetworkAdapterRegistry"),
    "NetworkExportResult": ("gridalyn.twin.adapters", "NetworkExportResult"),
    "NetworkIntegrityReport": ("gridalyn.twin.network", "NetworkIntegrityReport"),
    "NetworkModel": ("gridalyn.twin.network", "NetworkModel"),
    "NetworkModelRepository": ("gridalyn.twin.network", "NetworkModelRepository"),
    "NetworkSourceAdapter": ("gridalyn.twin.adapters", "NetworkSourceAdapter"),
    "SemanticGraphRepository": ("gridalyn.twin.semantic", "SemanticGraphRepository"),
    "SyntheticPandapowerAdapter": (
        "gridalyn.twin.adapters",
        "SyntheticPandapowerAdapter",
    ),
    "UnknownNetworkAdapterError": (
        "gridalyn.twin.adapters",
        "UnknownNetworkAdapterError",
    ),
    "build_network_adapter_validation_report": (
        "gridalyn.twin.adapters",
        "build_network_adapter_validation_report",
    ),
    "build_semantic_graph": ("gridalyn.twin.semantic", "build_semantic_graph"),
    "default_network_adapter_registry": (
        "gridalyn.twin.adapters",
        "default_network_adapter_registry",
    ),
    "describe_network_source_adapter": (
        "gridalyn.twin.adapters",
        "describe_network_source_adapter",
    ),
    "north_america_profile": ("gridalyn.twin.semantic", "north_america_profile"),
    "validate_semantic_graph": ("gridalyn.twin.semantic", "validate_semantic_graph"),
    "write_network_adapter_validation_report": (
        "gridalyn.twin.adapters",
        "write_network_adapter_validation_report",
    ),
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str):
    if name in _LAZY_EXPORTS:
        module_name, attr_name = _LAZY_EXPORTS[name]
        value = getattr(import_module(module_name), attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module 'gridalyn.twin' has no attribute {name!r}")


def __dir__() -> list[str]:
    """List the module namespace plus every lazily exported public name.

    Returns:
        Sorted names, so ``dir()`` and :func:`inspect.getmembers` see the
        lazy exports that ``__getattr__`` resolves on demand.
    """
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
