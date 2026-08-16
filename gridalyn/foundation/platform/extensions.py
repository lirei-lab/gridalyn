"""Generic extension engine for the Gridalyn platform.

Milestone 8's foundation: a single, stdlib-only registration engine that any
per-role registry (power-flow backend, surrogate, policy, observation producer,
network adapter, and the future data-source / stage-template contracts) can
wrap or delegate to. It knows nothing about roles — descriptors are passed in
as plain data, so ``foundation`` imports nothing from higher layers.

The module must stay stdlib-only and import nothing from gridalyn (AST-pinned
by ``tests/test_extensions.py::TestStdlibOnly``), which keeps ``foundation``
the sole stdlib layer. Capability-readiness of an extension is therefore a
caller-level concern (the CLI / runner, which may import
``gridalyn.foundation.platform.capabilities``), never this module's.

**The governing principle** (design ``.planning/explorations/2026-08-15-
extension-framework-design.md``): a component may be *discoverable*, but it is
never *silent*. Every extension that participates in a run is declared,
versioned and recorded in provenance. This module ships the descriptor, the
generic registry, the provenance snapshot, and — since Phase 15 — the
entry-point discovery and declared-only lazy loader (``list_installed_extensions``
for awareness without importing, ``load_entry_point_extensions`` for declared-
only resolution).
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from types import ModuleType
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


@dataclass(frozen=True)
class EntryPointMetadata:
    """Metadata of an installed entry point, without importing its module.

    Attributes:
        name: Entry-point name — the extension ID in the extensions group.
        value: Raw entry-point value (``"module"`` or ``"module:attr"``).
        module: Module name the entry point targets.
        attr: Attribute name within the module, if the value names one.
        distribution: Distribution the entry point ships with, else None.
        version: Distribution version, else empty.
    """

    name: str
    value: str
    module: str
    attr: str | None
    distribution: str | None
    version: str = ""


DEFAULT_EXTENSIONS_GROUP = "gridalyn.extensions"

#: Name of the extension-export convention a loadable module must expose.
FACTORY_ATTR = "factory"
DESCRIPTOR_ATTR = "descriptor"
#: Optional module attribute naming capabilities an extension needs to serve.
REQUIRED_CAPABILITIES_ATTR = "REQUIRED_CAPABILITIES"


def list_entry_point_metadata(group: str) -> list[EntryPointMetadata]:
    """Return metadata for every entry point in a group, importing nothing.

    The awareness primitive behind extension discovery: walking a group tells
    you what is installed without loading any module, so listing stays cheap
    and side-effect free. A missing group yields an empty list.

    Args:
        group: The entry-point group (e.g. ``"gridalyn.extensions"``).

    Returns:
        One metadata record per entry point, sorted by name.
    """
    try:
        selected = importlib.metadata.entry_points(group=group)
    except TypeError:  # pragma: no cover - Python < 3.10 compatibility
        selected = [ep for ep in importlib.metadata.entry_points() if ep.group == group]
    records: list[EntryPointMetadata] = []
    for ep in selected:
        module, sep, attr = ep.value.partition(":")
        records.append(
            EntryPointMetadata(
                name=ep.name,
                value=ep.value,
                module=module,
                attr=attr if sep else None,
                distribution=ep.dist.name if ep.dist else None,
                version=ep.dist.version if ep.dist else "",
            )
        )
    return sorted(records, key=lambda record: record.name)


def list_installed_extensions(
    group: str = DEFAULT_EXTENSIONS_GROUP,
) -> list[ExtensionDescriptor]:
    """Report installed extensions in an entry-point group without importing.

    The awareness path (``gridalyn extension list``): a component is visible
    because its package declares an entry point in the group, not because any
    module was loaded. Resolution still requires an explicit declaration — see
    :func:`load_entry_point_extensions`. ``role`` is unknown until the module
    is loaded, so it reads empty here; this is a roster, not a resolution.

    Args:
        group: The entry-point group to walk.

    Returns:
        One descriptor per installed entry point (``source="entry_point"``),
        sorted by extension ID, with no module imported.
    """
    descriptors: list[ExtensionDescriptor] = []
    for record in list_entry_point_metadata(group):
        descriptors.append(
            ExtensionDescriptor(
                extension_id=record.name,
                role="",
                name=record.name,
                version=record.version,
                contract_version="1",
                source="entry_point",
                entry_point_group=group,
            )
        )
    return descriptors


def _module_file_hash(module: ModuleType) -> str | None:
    """Return a sha256 of the module's source file, if one exists.

    Args:
        module: An imported module.

    Returns:
        The hex digest of the module's ``__file__`` contents, or None when the
        module has no source file (e.g. a built-in module).
    """
    source_file = getattr(module, "__file__", None)
    if not source_file:
        return None
    try:
        with open(source_file, "rb") as handle:  # noqa: PTH123 - stdlib path
            return hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return None


def load_entry_point_extensions(
    group: str,
    declared_ids: Iterable[str],
    *,
    registry: ExtensionRegistry | None = None,
) -> list[ExtensionDescriptor]:
    """Load and register ONLY the declared extensions from an entry-point group.

    The resolution path: a project (or CLI caller) declares which extension
    IDs it wants; this imports exactly those modules and registers each under
    ``source="entry_point"`` with its ``entry_point_group`` and a content
    ``module_hash``. Ambient entries in the group are never loaded — awareness
    (:func:`list_installed_extensions`) and resolution are separate.

    The module convention: an extension module exposes ``factory`` (a callable
    returning the role's component) and ``descriptor`` (an
    :class:`ExtensionDescriptor`). The entry-point name is the extension ID:
    the descriptor's ``extension_id`` is stamped to ``record.name`` so what is
    registered always matches the ID the caller declared, and ``source`` to
    ``"entry_point"`` because the provenance of HOW it was loaded is the
    loader's fact, not the module's claim. Capability readiness
    (``REQUIRED_CAPABILITIES``) is a caller-level check (a layer that may
    import ``gridalyn.foundation.platform.capabilities``) — this engine is
    stdlib-only and never inspects optional-module availability itself.

    Args:
        group: The entry-point group to resolve against.
        declared_ids: The extension IDs to load — only these are imported.
        registry: Registry to register into. Defaults to
            :data:`DEFAULT_REGISTRY`; pass a fresh instance to resolve without
            mutating the process-global default (e.g. validation).

    Returns:
        The registered descriptors, sorted by extension ID.

    Raises:
        UnknownExtensionError: If a declared ID is not present in the group,
            naming the available IDs.
        ImportError: If a declared extension module cannot be imported or does
            not expose the ``factory``/``descriptor`` convention.
    """
    targets = registry or DEFAULT_REGISTRY
    by_name = {record.name: record for record in list_entry_point_metadata(group)}
    loaded: list[ExtensionDescriptor] = []
    for extension_id in declared_ids:
        record = by_name.get(extension_id)
        if record is None:
            available = ", ".join(sorted(by_name)) or "none registered"
            raise UnknownExtensionError(
                f"declared extension {extension_id!r} is not installed in "
                f"entry-point group {group!r} (available extensions: "
                f"{available}); declare an ID that is actually installed, or "
                "install the package that ships it"
            )
        module = importlib.import_module(record.module)
        factory = getattr(module, FACTORY_ATTR, None)
        descriptor = getattr(module, DESCRIPTOR_ATTR, None)
        if not callable(factory) or not isinstance(descriptor, ExtensionDescriptor):
            raise ImportError(
                f"extension {extension_id!r} module {record.module!r} must "
                f"expose a callable {FACTORY_ATTR!r} and an "
                f"ExtensionDescriptor {DESCRIPTOR_ATTR!r} to be loadable; "
                "see docs/platform/extensions.md for the module convention"
            )
        registered = replace(
            descriptor,
            extension_id=record.name,
            source="entry_point",
            entry_point_group=group,
            module_hash=_module_file_hash(module),
        )
        targets.register(factory, descriptor=registered, replace=True)
        loaded.append(registered)
    return sorted(loaded, key=lambda descriptor: descriptor.extension_id)


__all__ = [
    "DEFAULT_EXTENSIONS_GROUP",
    "DESCRIPTOR_ATTR",
    "DEFAULT_REGISTRY",
    "EntryPointMetadata",
    "ExtensionDescriptor",
    "ExtensionRegistration",
    "ExtensionRegistry",
    "ExtensionSource",
    "FACTORY_ATTR",
    "REQUIRED_CAPABILITIES_ATTR",
    "SUPPORTED_CONTRACT_VERSIONS",
    "UnknownExtensionError",
    "UnsupportedContractVersionError",
    "extension_provenance",
    "list_entry_point_metadata",
    "list_installed_extensions",
    "load_entry_point_extensions",
    "register_extension",
]
