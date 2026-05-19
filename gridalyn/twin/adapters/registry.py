"""Registry for network source adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from gridalyn.twin.adapters.cim import CimParquetAdapter
from gridalyn.twin.adapters.network import (
    NetworkAdapterDescriptor,
    NetworkSourceAdapter,
    SyntheticPandapowerAdapter,
    describe_network_source_adapter,
)


class UnknownNetworkAdapterError(KeyError):
    """Raised when a requested network adapter is not registered."""


@dataclass(frozen=True)
class NetworkAdapterRegistration:
    """Factory and descriptor for a registered network source adapter."""

    descriptor: NetworkAdapterDescriptor
    factory: Callable[..., NetworkSourceAdapter]


class NetworkAdapterRegistry:
    """Discover and instantiate network source adapters by stable ID."""

    def __init__(self) -> None:
        self._registrations: dict[str, NetworkAdapterRegistration] = {}

    def register(
        self,
        factory: Callable[..., NetworkSourceAdapter],
        *,
        descriptor: NetworkAdapterDescriptor | None = None,
        replace: bool = False,
    ) -> None:
        """Register an adapter factory."""
        adapter_descriptor = descriptor or describe_network_source_adapter(factory)
        if adapter_descriptor.adapter_id in self._registrations and not replace:
            raise ValueError(f"Network adapter already registered: {adapter_descriptor.adapter_id}")
        self._registrations[adapter_descriptor.adapter_id] = NetworkAdapterRegistration(
            descriptor=adapter_descriptor,
            factory=factory,
        )

    def get_descriptor(self, adapter_id: str) -> NetworkAdapterDescriptor:
        """Return descriptor metadata for a registered adapter."""
        return self._registration(adapter_id).descriptor

    def list_descriptors(self) -> list[NetworkAdapterDescriptor]:
        """Return registered adapter descriptors sorted by adapter ID."""
        return [
            registration.descriptor
            for _, registration in sorted(self._registrations.items())
        ]

    def create(self, adapter_id: str, **kwargs: Any) -> NetworkSourceAdapter:
        """Instantiate a registered adapter."""
        return self._registration(adapter_id).factory(**kwargs)

    def _registration(self, adapter_id: str) -> NetworkAdapterRegistration:
        try:
            return self._registrations[adapter_id]
        except KeyError as exc:
            available = ", ".join(sorted(self._registrations)) or "none"
            raise UnknownNetworkAdapterError(
                f"Unknown network adapter: {adapter_id}. Available adapters: {available}"
            ) from exc


def default_network_adapter_registry() -> NetworkAdapterRegistry:
    """Build the default registry of network source adapters."""
    registry = NetworkAdapterRegistry()
    registry.register(SyntheticPandapowerAdapter)
    registry.register(CimParquetAdapter)
    return registry
