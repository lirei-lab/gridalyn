"""Route declared extensions to the registry of the role they serve (bd 4ky.8).

Diagnosis (2026-09-10, finding H7): the extension engine could load a declared
extension through the ``gridalyn.extensions`` entry-point group, but nothing in
a run ever did. ``spec.inputs.extensions`` had no reader outside tests, and an
extension that did load landed in the generic, role-agnostic registry, where no
role-specific consumer looks. An external package could not, in practice,
contribute a semantic capability to a study.

This module is the missing wire. :func:`register_declared_extensions`
resolves a project's declared extensions -- declared-only, never ambient -- and
hands each to the registry of the role it declares:

* ``semantic_capability``: the factory must return a
  :class:`~gridalyn.twin.semantic.vocabulary.SemanticCapability`. It is
  registered in the default semantic capability registry under the extension's
  source and version, so ``build_semantic_graph`` and the semantic validator
  resolve it by ID exactly as they resolve a shipped capability.
* ``interaction_protocol``: refused. The protocol set is closed by design
  (:mod:`gridalyn.operations.interaction.conversations`): a conversation's
  legality must not depend on what happens to be installed. An extension that
  claims the role fails loudly rather than loading and doing nothing.
* any other role: left in the generic registry, as before, where the runner
  records it in run provenance.

It lives in ``gridalyn.projects`` because routing needs both the foundation
engine and the twin registry, and only a layer above both may import them.

**Resolution happens in the process that builds.** The runner calls
:func:`register_declared_extensions` before any stage runs, so a declaration
that cannot be honoured fails the run up front and provenance records what was
contributed. A stage runs as its own process and inherits none of that, so a
stage that builds calls
:meth:`gridalyn.projects.scripting.ProjectScript.resolve_extensions` first.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from gridalyn.foundation.platform.extensions import (
        ExtensionDescriptor,
        ExtensionRegistry,
    )
    from gridalyn.twin.semantic.registry import SemanticCapabilityRegistry

#: The role of an extension whose factory returns a semantic capability.
SEMANTIC_CAPABILITY_ROLE = "semantic_capability"

#: The role an extension may not contribute: the protocol set is closed.
INTERACTION_PROTOCOL_ROLE = "interaction_protocol"


def register_extension_contribution(
    descriptor: ExtensionDescriptor,
    *,
    registry: ExtensionRegistry | None = None,
    capability_registry: SemanticCapabilityRegistry | None = None,
) -> bool:
    """Route one registered extension to the registry of the role it declares.

    Contributing the same extension twice is a no-op, so a process that
    resolves a project's declarations more than once -- the runner, then a stage
    helper run in the same interpreter -- does not trip over itself. A
    capability ID already held by a different source or version is refused:
    one ID names one declaration, and replacing it silently would change what a
    graph means without changing what its manifest says.

    Args:
        descriptor: The extension, as registered in ``registry``.
        registry: The generic engine the extension is registered in; defaults
            to its ``DEFAULT_REGISTRY``.
        capability_registry: The semantic capability registry to contribute
            to; defaults to the shared default.

    Returns:
        ``True`` when the extension was contributed to a role registry now,
        ``False`` when its role has no role registry or it was already there.

    Raises:
        ValueError: The extension declares ``interaction_protocol``, or its
            capability ID is already registered by a different source or
            version.
        TypeError: A ``semantic_capability`` extension's factory returns
            something other than a ``SemanticCapability``.
    """
    role = descriptor.role
    if role == INTERACTION_PROTOCOL_ROLE:
        raise ValueError(
            f"extension {descriptor.extension_id!r} declares role {role!r}, but "
            "interaction protocols are a closed set: a conversation's legality "
            "must not depend on what is installed "
            "(gridalyn.operations.interaction.conversations). Ship the protocol "
            "in gridalyn, or remove the extension from spec.inputs.extensions"
        )
    if role != SEMANTIC_CAPABILITY_ROLE:
        return False

    from gridalyn.foundation.platform import extensions as engine
    from gridalyn.twin.semantic.registry import default_semantic_capability_registry
    from gridalyn.twin.semantic.vocabulary import SemanticCapability

    component = (registry or engine.DEFAULT_REGISTRY).resolve(descriptor.extension_id)
    if not isinstance(component, SemanticCapability):
        raise TypeError(
            f"extension {descriptor.extension_id!r} declares role {role!r}, but "
            f"its factory returned {type(component).__name__}; a "
            f"{SEMANTIC_CAPABILITY_ROLE} factory must return a "
            "gridalyn.twin.semantic.vocabulary.SemanticCapability"
        )
    target = capability_registry or default_semantic_capability_registry()
    capability_id = component.capability_id
    if capability_id in target.list_ids():
        source = target.registration_source(capability_id)
        version = target.registration_version(capability_id)
        if source == descriptor.source and version == descriptor.version:
            return False
        raise ValueError(
            f"extension {descriptor.extension_id!r} contributes semantic "
            f"capability {capability_id!r} ({descriptor.source}, version "
            f"{descriptor.version}), but that ID is already registered by "
            f"{source!r} at version {version!r}; one capability ID names one "
            "declaration -- rename the capability or remove one of the two"
        )
    target.register(component, source=descriptor.source, version=descriptor.version)
    return True


def register_declared_extensions(project_or_path: Any) -> list[ExtensionDescriptor]:
    """Resolve a project's declared extensions and route each to its role.

    Args:
        project_or_path: The project declaring ``spec.inputs.extensions``: a
            loaded ``StudyProject``, its directory, or its ``project.yaml``.

    Returns:
        The resolved extension descriptors, sorted by ID; empty when the
        project declares none, so an undeclaring study is untouched.

    Raises:
        UnknownExtensionError: A declared ID is not installed.
        MissingCapabilityError: A declared extension's required capabilities
            are not importable.
        ValueError: A declared extension claims ``interaction_protocol``, or
            contributes a capability ID already held by another declaration.
        TypeError: A ``semantic_capability`` factory returns the wrong type.
    """
    from gridalyn.projects.model_inputs import resolve_declared_extensions

    descriptors = resolve_declared_extensions(project_or_path)
    for descriptor in descriptors:
        register_extension_contribution(descriptor)
    return descriptors


__all__ = [
    "INTERACTION_PROTOCOL_ROLE",
    "SEMANTIC_CAPABILITY_ROLE",
    "register_declared_extensions",
    "register_extension_contribution",
]
