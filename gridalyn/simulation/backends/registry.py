"""Registry for power-flow backends, resolved by explicit ID only.

Modelled on :mod:`gridalyn.twin.adapters.registry`: a frozen registration
pairing a descriptor with a factory, ``register(..., replace=False)``,
``get_descriptor``, ``list_descriptors()`` sorted by ID, ``create(id, **kwargs)``
and a located error enumerating the available IDs.

**There is no discovery.** No ``entry_points``, no plugin scan, no
environment-variable override. A backend that is not explicitly registered is
not resolvable, because an ambient plugin would change solved results without
appearing in ``provenance.powerflow_backend``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from gridalyn.foundation.platform.extensions import (
    SUPPORTED_CONTRACT_VERSIONS,
    ExtensionSource,
    UnsupportedContractVersionError,
)
from gridalyn.simulation.backends.contract import (
    DEFAULT_POWERFLOW_BACKEND_ID,
    PowerFlowBackend,
    PowerFlowBackendDescriptor,
    describe_powerflow_backend,
)
from gridalyn.simulation.backends.lightsim import LightSim2GridBackend
from gridalyn.simulation.backends.pandapower_native import PandapowerNativeBackend


class UnknownPowerFlowBackendError(KeyError):
    """Raised when a requested power-flow backend is not registered."""


@dataclass(frozen=True)
class PowerFlowBackendRegistration:
    """Factory, descriptor and registration source for a power-flow backend.

    Attributes:
        descriptor: What the registry records about the backend.
        factory: Callable producing a backend instance.
        source: Where the registration came from: ``"core"`` for the shipped
            defaults, ``"host"`` when registered through the host extension
            API (:func:`register_powerflow_backend_extension`). Recorded so
            ``provenance.powerflow_backend`` can name WHICH extension served
            the role rather than only that one exists.
        version: Optional semantic version recorded by a host extension;
            ``None`` for shipped backends and for registrations that do not
            declare one. Role descriptors have no version field, so this is
            the only place a version can be recorded.
    """

    descriptor: PowerFlowBackendDescriptor
    factory: Callable[..., PowerFlowBackend]
    source: ExtensionSource = "core"
    version: str | None = None


class PowerFlowBackendRegistry:
    """Resolve power-flow backends by stable, explicitly registered ID."""

    def __init__(self) -> None:
        """Create an empty registry."""
        self._registrations: dict[str, PowerFlowBackendRegistration] = {}

    def register(
        self,
        factory: Callable[..., PowerFlowBackend],
        *,
        descriptor: PowerFlowBackendDescriptor | None = None,
        replace: bool = False,
        source: ExtensionSource = "core",
        version: str | None = None,
    ) -> None:
        """Register a backend factory under its descriptor's ID.

        Args:
            factory: Callable returning a :class:`PowerFlowBackend`.
            descriptor: Descriptor to register under. Defaults to the one the
                factory declares.
            replace: Allow overwriting an already-registered ID.
            source: Registration source -- ``"core"`` for the shipped
                defaults, ``"host"`` when a host extension registers. Only
                the enumerated :data:`ExtensionSource` values are accepted,
                mirroring ``ExtensionDescriptor.__post_init__`` -- a typo'd
                source must not silently brand a core backend as an extension
                in the governed manifest.
            version: Optional semantic version when an extension supplies one.

        Raises:
            ValueError: If the ID is taken and ``replace`` is false. The
                message names the ID and the flag that would permit it.
            ValueError: If ``source`` is not one of the declared
                :data:`ExtensionSource` values.
        """
        backend_descriptor = descriptor or describe_powerflow_backend(factory)
        backend_id = backend_descriptor.backend_id
        if backend_descriptor.contract_version not in SUPPORTED_CONTRACT_VERSIONS:
            supported = ", ".join(sorted(SUPPORTED_CONTRACT_VERSIONS))
            raise UnsupportedContractVersionError(
                f"power-flow backend {backend_id!r} declares contract version "
                f"{backend_descriptor.contract_version!r}, but this engine "
                f"supports only: {supported}; upgrade or pin the extension to "
                "a supported contract version"
            )
        valid_sources: tuple[ExtensionSource, ...] = (
            "core",
            "host",
            "entry_point",
        )
        if source not in valid_sources:
            raise ValueError(
                f"power-flow backend {backend_id!r} declares unknown source "
                f"{source!r} (expected one of: "
                f"{', '.join(valid_sources)})"
            )
        if backend_id in self._registrations and not replace:
            raise ValueError(
                f"power-flow backend already registered: {backend_id} "
                "(pass replace=True to override it deliberately)"
            )
        self._registrations[backend_id] = PowerFlowBackendRegistration(
            descriptor=backend_descriptor,
            factory=factory,
            source=source,
            version=version,
        )

    def get_descriptor(self, backend_id: str) -> PowerFlowBackendDescriptor:
        """Return descriptor metadata for a registered backend.

        Args:
            backend_id: The registered ID.

        Returns:
            The registered descriptor.
        """
        return self._registration(backend_id).descriptor

    def registration_source(self, backend_id: str) -> ExtensionSource:
        """Return the source a backend was registered under.

        Args:
            backend_id: The registered ID.

        Returns:
            ``"core"`` for the shipped defaults, ``"host"`` for a host
            extension registration.
        """
        return self._registration(backend_id).source

    def registration_version(self, backend_id: str) -> str | None:
        """Return the semantic version an extension recorded, if any.

        Args:
            backend_id: The registered ID.

        Returns:
            The recorded version, or ``None`` when the registration did not
            supply one.
        """
        return self._registration(backend_id).version

    def list_descriptors(self) -> list[PowerFlowBackendDescriptor]:
        """Return registered backend descriptors sorted by backend ID.

        Returns:
            One descriptor per registration, ordered by ID so callers and
            manifests see a stable sequence.
        """
        return [
            registration.descriptor
            for _, registration in sorted(self._registrations.items())
        ]

    def create(self, backend_id: str, **kwargs: Any) -> PowerFlowBackend:
        """Instantiate a registered backend.

        Args:
            backend_id: The registered ID; no discovery, no fallback.
            **kwargs: Settings forwarded to the backend factory.

        Returns:
            A ready-to-use backend.

        Raises:
            UnknownPowerFlowBackendError: If ``backend_id`` is not registered.
            MissingCapabilityError: If the backend needs an optional extra
                that is not installed.
        """
        return self._registration(backend_id).factory(**kwargs)

    def _registration(self, backend_id: str) -> PowerFlowBackendRegistration:
        try:
            return self._registrations[backend_id]
        except KeyError as exc:
            available = ", ".join(sorted(self._registrations)) or "none registered"
            raise UnknownPowerFlowBackendError(
                f"unknown power-flow backend: {backend_id!r} "
                f"(available backends: {available}); backends resolve by "
                "explicit ID only -- register one with "
                "PowerFlowBackendRegistry.register before resolving it"
            ) from exc


_DEFAULT_POWERFLOW_BACKEND_REGISTRY: PowerFlowBackendRegistry | None = None


def default_powerflow_backend_registry() -> PowerFlowBackendRegistry:
    """Return the shared default registry of power-flow backends.

    The registry is built once and cached: external backends registered via
    :func:`register_powerflow_backend_extension` must stay resolvable through
    the default resolution path, which requires one persistent instance.
    Building it registers the shipped backends and constructs nothing, so it
    needs neither ``pandapower`` nor ``lightsim2grid``.
    """
    global _DEFAULT_POWERFLOW_BACKEND_REGISTRY
    if _DEFAULT_POWERFLOW_BACKEND_REGISTRY is None:
        registry = PowerFlowBackendRegistry()
        registry.register(PandapowerNativeBackend)
        registry.register(LightSim2GridBackend)
        _DEFAULT_POWERFLOW_BACKEND_REGISTRY = registry
    return _DEFAULT_POWERFLOW_BACKEND_REGISTRY


def register_powerflow_backend_extension(
    factory: Callable[..., PowerFlowBackend],
    *,
    descriptor: PowerFlowBackendDescriptor,
    replace: bool = False,
    version: str | None = None,
    registry: PowerFlowBackendRegistry | None = None,
) -> None:
    """Register an external power-flow backend (host API).

    A third-party backend conforms to the :class:`PowerFlowBackend` contract,
    carries a :class:`PowerFlowBackendDescriptor` with a supported
    ``contract_version``, and registers it here -- no edit to gridalyn's
    codebase required. Defaults to the shared default registry. The
    registration is recorded with ``source="host"`` so the run manifest can
    name the extension that served the backend role.

    Args:
        factory: Callable returning a :class:`PowerFlowBackend`.
        descriptor: Descriptor declaring the backend's identity and contract
            version.
        replace: Allow overwriting an already-registered ID.
        version: Optional semantic version of the extension.
        registry: Registry to register into; defaults to the shared default.
    """
    (registry or default_powerflow_backend_registry()).register(
        factory,
        descriptor=descriptor,
        replace=replace,
        source="host",
        version=version,
    )


def resolve_powerflow_backend(
    backend_id: str = DEFAULT_POWERFLOW_BACKEND_ID,
    **settings: Any,
) -> PowerFlowBackend:
    """Resolve one backend from the default registry by explicit ID.

    Args:
        backend_id: Registered backend ID. Defaults to the pandapower-native
            backend, which needs no optional extra.
        **settings: Settings forwarded to the backend factory.

    Returns:
        A ready-to-use backend.
    """
    return default_powerflow_backend_registry().create(backend_id, **settings)


def solve_power_flow(
    net: Any,
    *,
    backend_id: str = DEFAULT_POWERFLOW_BACKEND_ID,
    **kwargs: Any,
) -> None:
    """Solve ``net`` in place through a registry-resolved backend.

    The single-call convenience behind every power-flow call site in this
    repository. Call sites that solve in a loop should resolve a backend once
    with :func:`resolve_powerflow_backend` and reuse it instead.

    Args:
        net: A pandapower network, mutated in place with ``res_*`` tables.
        backend_id: Registered backend ID.
        **kwargs: Per-call solver keywords; they override the backend's own
            settings.
    """
    resolve_powerflow_backend(backend_id).solve(net, **kwargs)


__all__ = [
    "PowerFlowBackendRegistration",
    "PowerFlowBackendRegistry",
    "UnknownPowerFlowBackendError",
    "default_powerflow_backend_registry",
    "register_powerflow_backend_extension",
    "resolve_powerflow_backend",
    "solve_power_flow",
]
