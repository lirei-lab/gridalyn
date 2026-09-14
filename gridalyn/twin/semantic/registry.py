"""Registry of semantic capabilities, resolved by explicit ID only.

Before this module a semantic capability was an ``if "flexibility" in
capabilities`` repeated in ``mappings.py``, ``profile.py`` and the twin build,
and any other declared name was ignored in silence: measured 2026-09-10,
``profile_with_capabilities({"agent_interaction"})`` returned the core profile
without complaint. A capability now exists only by being registered here, and
resolving an unregistered ID raises :class:`UnknownSemanticCapabilityError`
naming the known set. That example name is itself a registered capability
since bd 4ky.7, so the tests measure the refusal with a name nothing
registers.

Modelled on the simulation registries (``backends``, ``surrogates``,
``policies``): explicit IDs, no discovery, ``register(..., replace=False)``,
and a ``registration_source`` that tells a core capability from one a host
registered through :func:`register_semantic_capability_extension`. It is not
one of the component registries gated by ``tests/test_registry_parity.py``: a
capability is a declaration, not a factory, so it has nothing to ``create``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from importlib import import_module

from gridalyn.foundation.platform.extensions import ExtensionSource
from gridalyn.twin.semantic.vocabulary import SemanticCapability

#: Version recorded for the capabilities gridalyn itself ships.
CORE_CAPABILITY_VERSION = "1"

#: Capabilities gridalyn ships, as ``id -> (module, attribute)``. Loaded when
#: the default registry is first built, not when this module is imported.
_CORE_CAPABILITIES: dict[str, tuple[str, str]] = {
    "agent_interaction": (
        "gridalyn.twin.semantic.capabilities.agent_interaction",
        "AGENT_INTERACTION_CAPABILITY",
    ),
    "flexibility": (
        "gridalyn.twin.semantic.capabilities.flexibility",
        "FLEXIBILITY_CAPABILITY",
    ),
}

_VALID_SOURCES: frozenset[str] = frozenset({"core", "host", "entry_point"})

_CAPABILITY_ID = re.compile(r"^[a-z][a-z0-9_-]*$")


class UnknownSemanticCapabilityError(ValueError):
    """Raised when a declared semantic capability is not registered."""


@dataclass(frozen=True)
class SemanticCapabilityRegistration:
    """A registered capability and who registered it.

    Attributes:
        capability: The declaration.
        source: ``core`` for shipped capabilities, ``host`` for ones registered
            through :func:`register_semantic_capability_extension`.
        version: Version of the declaration.
    """

    capability: SemanticCapability
    source: ExtensionSource
    version: str


def _unknown_message(unknown: Iterable[str], known: Iterable[str]) -> str:
    """Render the located error for unregistered capability IDs."""
    unknown_ids = sorted(unknown)
    noun = "capability" if len(unknown_ids) == 1 else "capabilities"
    return (
        f"unknown semantic {noun} {', '.join(repr(i) for i in unknown_ids)} "
        f"(known: {', '.join(sorted(known)) or 'none registered'}); register "
        "it with register_semantic_capability_extension or remove it from the "
        "declared capabilities"
    )


class SemanticCapabilityRegistry:
    """Hold semantic capabilities and resolve declared IDs to them."""

    def __init__(self) -> None:
        """Start with no capability registered."""
        self._registrations: dict[str, SemanticCapabilityRegistration] = {}
        self._revision = 0

    def register(
        self,
        capability: SemanticCapability,
        *,
        source: ExtensionSource = "core",
        version: str = CORE_CAPABILITY_VERSION,
        replace: bool = False,
    ) -> None:
        """Register a capability under its declared ID.

        Args:
            capability: The declaration to register.
            source: Who registers it; ``core`` for shipped capabilities.
            version: Version of the declaration.
            replace: Allow overwriting an already-registered ID.

        Raises:
            ValueError: The ID is malformed, the source unknown, or the ID is
                already registered and ``replace`` is false.
        """
        capability_id = capability.capability_id
        if not _CAPABILITY_ID.match(capability_id):
            raise ValueError(
                f"semantic capability id {capability_id!r} must match "
                f"{_CAPABILITY_ID.pattern}"
            )
        if source not in _VALID_SOURCES:
            raise ValueError(
                f"semantic capability {capability_id!r}: unknown source "
                f"{source!r} (known: {', '.join(sorted(_VALID_SOURCES))})"
            )
        existing = self._registrations.get(capability_id)
        if existing is not None and not replace:
            raise ValueError(
                f"semantic capability {capability_id!r} is already registered "
                f"(source {existing.source!r}); pass replace=True to overwrite it"
            )
        self._registrations[capability_id] = SemanticCapabilityRegistration(
            capability=capability, source=source, version=version
        )
        self._revision += 1

    @property
    def revision(self) -> int:
        """Return a counter that changes whenever a registration is made."""
        return self._revision

    def list_ids(self) -> tuple[str, ...]:
        """Return every registered capability ID, sorted."""
        return tuple(sorted(self._registrations))

    def get(self, capability_id: str) -> SemanticCapability:
        """Return the capability registered under ``capability_id``.

        Raises:
            UnknownSemanticCapabilityError: The ID is not registered.
        """
        return self._registration(capability_id).capability

    def registration_source(self, capability_id: str) -> ExtensionSource:
        """Return who registered ``capability_id``: ``core`` or ``host``.

        Raises:
            UnknownSemanticCapabilityError: The ID is not registered.
        """
        return self._registration(capability_id).source

    def registration_version(self, capability_id: str) -> str:
        """Return the version ``capability_id`` was registered with.

        Raises:
            UnknownSemanticCapabilityError: The ID is not registered.
        """
        return self._registration(capability_id).version

    def resolve(self, capability_ids: Iterable[str]) -> tuple[SemanticCapability, ...]:
        """Resolve declared IDs to capabilities, in ID order.

        Args:
            capability_ids: Declared capability IDs; duplicates collapse.

        Returns:
            The capabilities sorted by ID, so composition order never depends
            on declaration order.

        Raises:
            UnknownSemanticCapabilityError: Naming every unregistered ID and the
                registered set.
        """
        requested = sorted(set(capability_ids))
        unknown = [cid for cid in requested if cid not in self._registrations]
        if unknown:
            raise UnknownSemanticCapabilityError(
                _unknown_message(unknown, self._registrations)
            )
        return tuple(self._registrations[cid].capability for cid in requested)

    def _registration(self, capability_id: str) -> SemanticCapabilityRegistration:
        try:
            return self._registrations[capability_id]
        except KeyError:
            raise UnknownSemanticCapabilityError(
                _unknown_message([capability_id], self._registrations)
            ) from None


_DEFAULT_SEMANTIC_CAPABILITY_REGISTRY: SemanticCapabilityRegistry | None = None


def default_semantic_capability_registry() -> SemanticCapabilityRegistry:
    """Return the shared default registry, with gridalyn's capabilities loaded.

    Built once and cached, so a capability registered through
    :func:`register_semantic_capability_extension` stays resolvable on the
    default path. Building it imports each shipped capability module.
    """
    global _DEFAULT_SEMANTIC_CAPABILITY_REGISTRY
    if _DEFAULT_SEMANTIC_CAPABILITY_REGISTRY is None:
        registry = SemanticCapabilityRegistry()
        for capability_id, (module_name, attribute) in _CORE_CAPABILITIES.items():
            capability = getattr(import_module(module_name), attribute)
            if capability.capability_id != capability_id:
                raise ValueError(
                    f"{module_name}.{attribute} declares capability "
                    f"{capability.capability_id!r}, registered as {capability_id!r}"
                )
            registry.register(capability, source="core")
        _DEFAULT_SEMANTIC_CAPABILITY_REGISTRY = registry
    return _DEFAULT_SEMANTIC_CAPABILITY_REGISTRY


def register_semantic_capability_extension(
    capability: SemanticCapability,
    *,
    version: str,
    replace: bool = False,
    registry: SemanticCapabilityRegistry | None = None,
) -> None:
    """Register an external semantic capability (host API).

    The registration is recorded with ``source="host"``, so a manifest or a
    reader can tell it from a capability gridalyn ships.

    Args:
        capability: The declaration to register.
        version: Version of the extension's declaration.
        replace: Allow overwriting an already-registered ID.
        registry: Registry to register into; defaults to the shared default.
    """
    (registry or default_semantic_capability_registry()).register(
        capability, source="host", version=version, replace=replace
    )


__all__ = [
    "CORE_CAPABILITY_VERSION",
    "SemanticCapabilityRegistration",
    "SemanticCapabilityRegistry",
    "UnknownSemanticCapabilityError",
    "default_semantic_capability_registry",
    "register_semantic_capability_extension",
]
