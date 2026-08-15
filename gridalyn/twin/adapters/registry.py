"""Registry for network source adapters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from gridalyn.foundation.platform.extensions import (
    SUPPORTED_CONTRACT_VERSIONS,
    UnsupportedContractVersionError,
)
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
        if adapter_descriptor.contract_version not in SUPPORTED_CONTRACT_VERSIONS:
            supported = ", ".join(sorted(SUPPORTED_CONTRACT_VERSIONS))
            raise UnsupportedContractVersionError(
                f"network adapter {adapter_descriptor.adapter_id!r} declares "
                f"contract version {adapter_descriptor.contract_version!r}, "
                f"but this engine supports only: {supported}; upgrade or pin "
                "the extension to a supported contract version"
            )
        if adapter_descriptor.adapter_id in self._registrations and not replace:
            raise ValueError(
                f"Network adapter already registered: {adapter_descriptor.adapter_id}"
            )
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


_DEFAULT_NETWORK_ADAPTER_REGISTRY: NetworkAdapterRegistry | None = None


def default_network_adapter_registry() -> NetworkAdapterRegistry:
    """Return the shared default registry of network source adapters.

    Built once and cached so external adapters registered via
    :func:`register_network_adapter_extension` stay resolvable through the
    default path. Holds the synthetic pandapower adapter and the CIM parquet
    adapter.
    """
    global _DEFAULT_NETWORK_ADAPTER_REGISTRY
    if _DEFAULT_NETWORK_ADAPTER_REGISTRY is None:
        registry = NetworkAdapterRegistry()
        registry.register(SyntheticPandapowerAdapter)
        registry.register(CimParquetAdapter)
        _DEFAULT_NETWORK_ADAPTER_REGISTRY = registry
    return _DEFAULT_NETWORK_ADAPTER_REGISTRY


def register_network_adapter_extension(
    factory: Callable[..., NetworkSourceAdapter],
    *,
    descriptor: NetworkAdapterDescriptor,
    replace: bool = False,
    registry: NetworkAdapterRegistry | None = None,
) -> None:
    """Register an external network source adapter (host API).

    A third-party adapter conforms to the :class:`NetworkSourceAdapter`
    contract, carries a :class:`NetworkAdapterDescriptor` with a supported
    ``contract_version``, and registers it here — no edit to gridalyn's
    codebase required. Defaults to the shared default registry.
    """
    (registry or default_network_adapter_registry()).register(
        factory, descriptor=descriptor, replace=replace
    )
