"""Generic extension engine for the Gridalyn platform.

Milestone 8's foundation: a single, stdlib-only registration engine that any
per-role registry (power-flow backend, surrogate, policy, observation producer,
network adapter, and the future data-source / stage-template contracts) can
wrap or delegate to. It knows nothing about roles — descriptors are passed in
as plain data, so ``foundation`` imports nothing from higher layers.

**The governing principle** (design ``.planning/explorations/2026-08-15-
extension-framework-design.md``): a component may be *discoverable*, but it is
never *silent*. Every extension that participates in a run is declared,
versioned and recorded in provenance. This module ships the descriptor and the
generic registry; registration sources and the ``extension_provenance()``
snapshot are added by the follow-up plan in the same phase.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

#: Where a registration came from. ``core`` = shipped in gridalyn; ``host`` =
#: registered at runtime by the embedding application; ``entry_point`` =
#: discovered from a declared entry point / namespace walk (Phase 15 wires it).
ExtensionSource = Literal["core", "host", "entry_point"]

#: The contract versions this engine supports. A descriptor whose
#: ``contract_version`` is not in this set is rejected at registration with a
#: located error — there is no silent fallback, because an incompatible
#: extension would change results without appearing correctly in provenance.
SUPPORTED_CONTRACT_VERSIONS: frozenset[str] = frozenset({"1"})


@dataclass(frozen=True)
class ExtensionDescriptor:
    """Identity, provenance and compatibility metadata for an extension.

    Attributes:
        extension_id: Stable ID the extension resolves by. Explicit and
            declared at registration — never discovered ambiently.
        role: The contract the extension serves (e.g. ``powerflow_backend``,
            ``observation_producer``). The engine stores it as data only; it
            does not interpret roles.
        name: Human-readable name for reports and manifests.
        version: Extension version string, recorded verbatim in provenance.
        contract_version: The version of the role contract this extension
            conforms to. The engine refuses descriptors whose
            ``contract_version`` it does not support (no silent fallback).
        source: Where the registration came from (``core``/``host``/
            ``entry_point``).
        entry_point_group: The entry-point group or namespace an
            ``entry_point``-sourced extension was discovered from, else None.
        module_hash: Content hash of the extension module, when known, so
            provenance can pin exactly what was loaded.
    """

    extension_id: str
    role: str
    name: str = ""
    version: str = "0"
    contract_version: str = "1"
    source: ExtensionSource = "core"
    entry_point_group: str | None = None
    module_hash: str | None = None

    def __post_init__(self) -> None:
        """Validate the descriptor's enumerated fields at construction.

        Raises:
            ValueError: If ``source`` is not one of the declared
                :data:`ExtensionSource` values.
        """
        valid_sources = ("core", "host", "entry_point")
        if self.source not in valid_sources:
            raise ValueError(
                f"extension {self.extension_id!r} declares unknown source "
                f"{self.source!r} (expected one of: {', '.join(valid_sources)})"
            )

    def as_dict(self) -> dict[str, Any]:
        """Return a plain-JSON view of the descriptor for provenance.

        Returns:
            A ``dict`` with only str/None values, so it can be embedded in the
            run manifest without a custom encoder.
        """
        return {
            "extension_id": self.extension_id,
            "role": self.role,
            "name": self.name,
            "version": self.version,
            "contract_version": self.contract_version,
            "source": self.source,
            "entry_point_group": self.entry_point_group,
            "module_hash": self.module_hash,
        }


@dataclass(frozen=True)
class ExtensionRegistration:
    """Factory and descriptor for a registered extension."""

    descriptor: ExtensionDescriptor
    factory: Callable[..., Any]


class UnknownExtensionError(KeyError):
    """Raised when a requested extension is not registered."""


class UnsupportedContractVersionError(ValueError):
    """Raised when a descriptor's contract version is not supported."""


class ExtensionRegistry:
    """Generic registry of extensions by stable, explicitly registered ID.

    The engine is role-agnostic: it stores descriptors plus factories keyed
    by ``extension_id`` and never inspects what a factory returns. Per-role
    registries keep their own public shape and may wrap this engine or reuse
    the same conventions.
    """

    def __init__(self) -> None:
        """Start with no registrations; nothing is discovered ambiently."""
        self._registrations: dict[str, ExtensionRegistration] = {}

    def register(
        self,
        factory: Callable[..., Any],
        *,
        descriptor: ExtensionDescriptor,
        replace: bool = False,
    ) -> None:
        """Register an extension factory under its descriptor's ID.

        Args:
            factory: Callable returning the role's component. The engine does
                not call or type-check it at registration time.
            descriptor: The extension's identity/provenance metadata.
            replace: Allow overwriting an already-registered ID.

        Raises:
            ValueError: If the ID is taken and ``replace`` is false. The
                message names the ID and the flag that would permit it.
            UnsupportedContractVersionError: If ``descriptor.contract_version``
                is not in :data:`SUPPORTED_CONTRACT_VERSIONS`.
        """
        if descriptor.contract_version not in SUPPORTED_CONTRACT_VERSIONS:
            supported = ", ".join(sorted(SUPPORTED_CONTRACT_VERSIONS))
            raise UnsupportedContractVersionError(
                f"extension {descriptor.extension_id!r} declares contract "
                f"version {descriptor.contract_version!r}, but this engine "
                f"supports only: {supported}; upgrade or pin the extension to "
                "a supported contract version"
            )
        if descriptor.extension_id in self._registrations and not replace:
            raise ValueError(
                f"extension already registered: {descriptor.extension_id!r} "
                f"for role {descriptor.role!r} "
                "(pass replace=True to override it deliberately)"
            )
        self._registrations[descriptor.extension_id] = ExtensionRegistration(
            descriptor=descriptor,
            factory=factory,
        )

    def get_descriptor(self, extension_id: str) -> ExtensionDescriptor:
        """Return the descriptor metadata for a registered extension.

        Args:
            extension_id: The registered ID.

        Returns:
            The registered descriptor.

        Raises:
            UnknownExtensionError: If ``extension_id`` is not registered.
        """
        return self._registration(extension_id).descriptor

    def list_descriptors(self) -> list[ExtensionDescriptor]:
        """Return registered descriptors sorted by extension ID.

        Returns:
            One descriptor per registration, ordered by ID so callers and
            manifests see a stable sequence.
        """
        return [
            registration.descriptor
            for _, registration in sorted(self._registrations.items())
        ]

    def resolve(self, extension_id: str, **kwargs: Any) -> Any:
        """Instantiate a registered extension by calling its factory.

        Args:
            extension_id: The registered ID; no discovery, no fallback.
            **kwargs: Settings forwarded to the extension factory.

        Returns:
            Whatever the factory returns (the role's component).

        Raises:
            UnknownExtensionError: If ``extension_id`` is not registered.
        """
        return self._registration(extension_id).factory(**kwargs)

    def _registration(self, extension_id: str) -> ExtensionRegistration:
        try:
            return self._registrations[extension_id]
        except KeyError as exc:
            available = ", ".join(sorted(self._registrations)) or "none registered"
            raise UnknownExtensionError(
                f"unknown extension: {extension_id!r} "
                f"(available extensions: {available}); extensions resolve by "
                "explicit ID only -- register one with "
                "ExtensionRegistry.register before resolving it"
            ) from exc


#: The shared default registry. The runner and embedding applications register
#: core/host/entry_point extensions here, and ``extension_provenance()``
#: snapshots it into the run manifest. Created empty at import time (cheap,
#: no discovery, no optional imports) so importing the package stays clean.
DEFAULT_REGISTRY = ExtensionRegistry()


def register_extension(
    factory: Callable[..., Any],
    *,
    descriptor: ExtensionDescriptor,
    replace: bool = False,
) -> None:
    """Register an extension into the default registry (host API).

    This is the public registration surface for embedding applications and for
    gridalyn's own wiring: a third-party component conforms to a role contract,
    builds an :class:`ExtensionDescriptor`, and registers it here — no edit to
    the gridalyn codebase required.

    Args:
        factory: Callable returning the role's component.
        descriptor: The extension's identity/provenance metadata.
        replace: Allow overwriting an already-registered ID.

    Raises:
        ValueError: If the ID is taken and ``replace`` is false.
        UnsupportedContractVersionError: If the contract version is unsupported.
    """
    DEFAULT_REGISTRY.register(factory, descriptor=descriptor, replace=replace)


def extension_provenance(
    *registries: ExtensionRegistry,
) -> list[dict[str, Any]]:
    """Return a JSON-native provenance snapshot of registered extensions.

    Args:
        *registries: Registries to snapshot. Defaults to
            :data:`DEFAULT_REGISTRY` when none are given.

    Returns:
        One plain dict per registered extension — ``extension_id``, ``role``,
        ``name``, ``version``, ``contract_version``, ``source``,
        ``entry_point_group``, ``module_hash`` — sorted by ``extension_id``.
        Side-effect free: imports nothing and performs no discovery.
    """
    targets = registries or (DEFAULT_REGISTRY,)
    descriptors: list[ExtensionDescriptor] = []
    for registry in targets:
        descriptors.extend(registry.list_descriptors())
    descriptors.sort(key=lambda d: d.extension_id)
    return [descriptor.as_dict() for descriptor in descriptors]


__all__ = [
    "DEFAULT_REGISTRY",
    "ExtensionDescriptor",
    "ExtensionRegistration",
    "ExtensionRegistry",
    "ExtensionSource",
    "SUPPORTED_CONTRACT_VERSIONS",
    "UnknownExtensionError",
    "UnsupportedContractVersionError",
    "extension_provenance",
    "register_extension",
]
