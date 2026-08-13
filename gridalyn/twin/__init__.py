"""Digital-twin model, observation, adapter, and semantic graph facade.

This is one of the advertised public layer facades (see
``tests/test_public_api_surface.py``), so it declares what the layer *is*, not
merely what other in-repo modules happen to import from it. The layer owns four
things and each is reachable here: the canonical model (:class:`NetworkModel`
and its identity), the repository that loads and validates it, the source
adapters that produce it, and — since the observation contract came down from
``gridalyn.simulation`` — the observed state read back off a solved network.

The criterion every entry below satisfies, derived from the entries that were
already here: a name belongs on this facade when it is a public entry point of
the layer, or a type that appears in the signature of one. That is why
:class:`NetworkIntegrityReport`, :class:`DownstreamAssets` and
:class:`ModelIdentity` are here despite no in-repo module importing them from
this path — they are what :class:`NetworkModelRepository` hands back, and this
facade is an advertised SDK surface rather than a record of internal imports.

``ModelAuthoritySet`` and ``ModelProfile`` are exported because both source
adapters' ``authority_sets()`` and ``profiles()`` return them — the criterion
above, which they were already recorded as meeting. Like every other entry
they resolve through a sub-facade: ``gridalyn.twin.adapters`` re-exports them
from the implementation module ``gridalyn.twin.adapters.authority``, and this
facade points at ``gridalyn.twin.adapters``, never at the implementation.
(The module path moved from ``…adapters.cim`` to ``…adapters.authority`` in
review cycle 1 of Phase 11 — see that module's docstring for why.)

Names deliberately NOT re-exported here, each for a measured reason:

* ``BASE_TABLE_SCHEMAS`` / ``table_schema`` (``gridalyn.twin.network.schema``)
  — the declared column contract between the repository and its adapters. It
  appears in no public signature and both of its production consumers live
  *inside* this layer, so promoting it would advertise an internal contract as
  SDK surface.
* ``AS_OF_ABSENT_REASON`` / ``SCENARIO_TIME_ABSENT_REASON`` — documentation
  constants that travel with their fields, not API.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "CimParquetAdapter": ("gridalyn.twin.adapters", "CimParquetAdapter"),
    "ConnectedEquipment": ("gridalyn.twin.network", "ConnectedEquipment"),
    "DownstreamAssets": ("gridalyn.twin.network", "DownstreamAssets"),
    "ModelAuthoritySet": ("gridalyn.twin.adapters", "ModelAuthoritySet"),
    "ModelIdentity": ("gridalyn.twin.network", "ModelIdentity"),
    "ModelProfile": ("gridalyn.twin.adapters", "ModelProfile"),
    "NetworkAdapterDescriptor": ("gridalyn.twin.adapters", "NetworkAdapterDescriptor"),
    "NetworkAdapterRegistry": ("gridalyn.twin.adapters", "NetworkAdapterRegistry"),
    "NetworkExportResult": ("gridalyn.twin.adapters", "NetworkExportResult"),
    "NetworkIntegrityReport": ("gridalyn.twin.network", "NetworkIntegrityReport"),
    "NetworkModel": ("gridalyn.twin.network", "NetworkModel"),
    "NetworkModelRepository": ("gridalyn.twin.network", "NetworkModelRepository"),
    "NetworkObservation": ("gridalyn.twin.observation", "NetworkObservation"),
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
    "observe_network": ("gridalyn.twin.observation", "observe_network"),
    "validate_semantic_graph": ("gridalyn.twin.semantic", "validate_semantic_graph"),
    "write_network_adapter_validation_report": (
        "gridalyn.twin.adapters",
        "write_network_adapter_validation_report",
    ),
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str) -> Any:
    """Lazily resolve a digital-twin symbol from its implementation module.

    Args:
        name: Public attribute requested on ``gridalyn.twin``.

    Returns:
        The resolved attribute, cached into module globals for free re-access.

    Raises:
        AttributeError: If ``name`` is not a known digital-twin symbol.
    """
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
