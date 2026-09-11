"""Semantic profile definitions for Gridalyn digital-twin graphs.

The **model-first core** -- generic IEC CIM topology, Brick/ASHRAE premises,
scenario and run provenance -- is declared here as data: namespaces, semantic
types, and relationships with their axioms (one predicate, a domain, a range,
optionally a cardinality). On-demand capabilities such as ``flexibility`` are
resolved by explicit ID through :mod:`gridalyn.twin.semantic.registry` and
composed over the core by :func:`profile_with_capabilities`.

**Re-based 2026-09-10.** Before, the capability was a hardcoded
``if "flexibility"`` here, in ``mappings.py`` and in the twin build; an unknown
capability name was ignored in silence; and relationships were a list of names
with no declared predicate. Measured on the shipped graph,
``ENABLES`` and ``HAS_FLEXIBILITY_RESOURCE`` each carried two IRIs and the
10 357 topology edges used the class ``cim:ConnectivityNode`` as their
predicate. Composition now rejects those conditions, so the profile a graph is
built and validated against states, for every relationship, the one predicate
its edges carry. The byte-identity of the pre-Phase-21 profile (R7) was given
up deliberately in the same re-base: the profile gained the axioms it lacked.

**Persistent IRIs (2026-09-11).** gridalyn's own vocabularies moved off the
unresolvable ``gridalyn.local`` host to :data:`GRIDALYN_ONTOLOGY_BASE` on
w3id.org: ``dt:`` for the digital-twin core, and ``flexint:`` for flexibility
markets, contracts and agent interaction, which replaces ``cls:``. ``cim:`` is
now ``http://iec.ch/TC57/CIM100#``, the namespace North American distribution
tooling emits; the CIM18 spellings are ingest aliases, never emitted. Every
term that changed is a declared :class:`TermAlias`, resolvable for one release
through :func:`resolve_deprecated_term`.

``SEMANTIC_TYPE`` stays the **shared canonical vocabulary** for every generator
(the semantic graph and the network-impact surrogate) -- a spelling registry,
not an emission bias.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, get_args

from gridalyn.twin.semantic.registry import (
    SemanticCapabilityRegistry,
    default_semantic_capability_registry,
)
from gridalyn.twin.semantic.vocabulary import (
    RelationshipSpec,
    ScenarioCountRule,
    SemanticCapability,
    TermAlias,
)

#: Semantic profiles gridalyn defines. A consumer that records which profile it
#: speaks -- an operation context, for one -- validates against this set.
SemanticProfileId = Literal["north_america"]
SEMANTIC_PROFILE_IDS: tuple[SemanticProfileId, ...] = get_args(SemanticProfileId)

NAMESPACES = {
    "cim": "http://iec.ch/TC57/CIM100#",
    "brick": "https://brickschema.org/schema/Brick#",
    # Aspirational — declared for future/imported use; not currently emitted.
    "s223": "http://data.ashrae.org/standard223#",
    # Aspirational — not currently emitted (Green Button appears only as the
    # source_standard string on dt:TimeSeriesDataset).
    "gb": "https://www.greenbuttondata.org/ns#",
    "dt": "https://w3id.org/gridalyn/ontology/digital-twin#",
}

#: Base of every vocabulary gridalyn defines itself. Registered at w3id.org,
#: which redirects each vocabulary to its documentation page and Turtle file.
GRIDALYN_ONTOLOGY_BASE = "https://w3id.org/gridalyn/ontology/"

#: Namespaces a graph written before 2026-09-11 may carry, by prefix. Kept to
#: read old artifacts; never bound in a profile, never emitted.
DEPRECATED_NAMESPACES: dict[str, str] = {
    "cls": "https://gridalyn.local/ontology/cls#",
    "dt": "https://gridalyn.local/ontology/digital-twin#",
    "ieee2030_5": "https://standards.ieee.org/ieee/2030.5#",
}

#: CIM namespaces other tools write, accepted on ingest and mapped to ``cim:``
#: term by term: CIM18 renamed and restructured classes, so only the terms in
#: :data:`CIM_INGEST_TERMS` -- the classes the model-first core emits -- map by
#: local name, and any other term is refused rather than guessed.
CIM_INGEST_NAMESPACES: tuple[str, ...] = (
    "http://cim.ucaiug.io/ns#",
    "https://cim.ucaiug.io/ns#",
    "http://cim.ucaiug.io/CIM101/draft#",
)
CIM_INGEST_TERMS: frozenset[str] = frozenset(
    {"ACLineSegment", "ConnectivityNode", "EnergyConsumer", "PowerTransformer"}
)

PRIMARY_STANDARDS: dict[str, tuple[str, ...]] = {
    "grid_topology": ("IEC CIM", "IEC 61970", "IEC 61968", "CIM100"),
    "buildings": ("ASHRAE 223", "Brick Schema"),
    "metering": ("Green Button", "NAESB ESPI"),
}

UNIT_CONVENTIONS: dict[str, str] = {
    "active_power": "kW or MW, explicit in property name",
    "reactive_power": "kvar or Mvar, explicit in property name",
    "voltage": "kV or pu, explicit in property name",
    "current": "kA, explicit in property name",
}

# SAREF is not integrated at all today -- no generator emits a `saref:` type,
# primary or crosswalk -- so a declared `crosswalk_only_namespaces` constraint
# had nothing to enforce and no reader checked it (removed 2026-08-19). If
# SAREF is integrated later, declare and enforce it alongside the real emitter.

CORE_SEMANTIC_TYPES: tuple[str, ...] = (
    "brick:Building",
    "cim:ACLineSegment",
    "cim:ConnectivityNode",
    "cim:EnergyConsumer",
    "cim:PowerTransformer",
    "dt:Scenario",
    "dt:SimulationRun",
    "dt:TimeSeriesDataset",
)

_TERMINAL_SHORTCUT = (
    "Local shortcut: CIM reaches a ConnectivityNode from equipment through a "
    "Terminal (Terminal.ConductingEquipment, Terminal.ConnectivityNode), and "
    "this graph collapses the Terminal. Until 2026-09-10 these edges carried "
    "the class IRI cim:ConnectivityNode as their predicate."
)

CORE_RELATIONSHIPS: tuple[RelationshipSpec, ...] = (
    RelationshipSpec(
        name="CONNECTED_TO",
        predicate="dt:connectedTo",
        domain=("cim:EnergyConsumer",),
        range=("cim:ConnectivityNode",),
        source_cardinality=(1, 1),
        note=_TERMINAL_SHORTCUT,
    ),
    RelationshipSpec(
        name="CONNECTS",
        predicate="dt:connects",
        domain=("cim:ACLineSegment",),
        range=("cim:ConnectivityNode",),
        source_cardinality=(2, 2),
        note=_TERMINAL_SHORTCUT,
    ),
    RelationshipSpec(
        name="FEEDS",
        predicate="dt:feeds",
        domain=("cim:PowerTransformer",),
        range=("cim:ConnectivityNode",),
        source_cardinality=(2, 2),
        note=_TERMINAL_SHORTCUT,
    ),
    RelationshipSpec(
        name="HAS_LOAD",
        predicate="dt:hasLoad",
        domain=("brick:Building",),
        range=("cim:EnergyConsumer",),
        source_cardinality=(1, 1),
    ),
    RelationshipSpec(
        name="INCLUDES_ASSET",
        predicate="dt:includesAsset",
        domain=("dt:Scenario",),
        range=("brick:Building",),
    ),
    RelationshipSpec(
        name="OBSERVES",
        predicate="dt:observes",
        domain=("dt:TimeSeriesDataset",),
        range=("dt:Scenario",),
    ),
    RelationshipSpec(
        name="PRODUCED",
        predicate="dt:produced",
        domain=("dt:SimulationRun",),
        range=("dt:TimeSeriesDataset",),
    ),
)

RELATIONSHIP_TYPES: list[str] = sorted(spec.name for spec in CORE_RELATIONSHIPS)

#: The capabilities a caller that declares none (``None``) receives: the graph
#: every pre-Phase-21 caller got.
LEGACY_DEFAULT_CAPABILITIES: frozenset[str] = frozenset({"flexibility"})


# Canonical semantic-type vocabulary shared by every generator (the semantic
# graph in mappings.py and the network-impact surrogate). A concept's one
# spelling lives here; generators import it instead of re-declaring divergent
# qnames (Phase 9, finding G10). The flexibility/DER keys
# (``flexibility_provider``, ``evse``, ``network_impact``) belong to the
# on-demand flexibility capability and are used by the surrogate and the
# capability's emitters, never by the model-first emission default.
SEMANTIC_TYPE: dict[str, str] = {
    "building": "brick:Building",
    "connectivity_node": "cim:ConnectivityNode",
    "energy_consumer": "cim:EnergyConsumer",
    "power_transformer": "cim:PowerTransformer",
    "flexibility_provider": "flexint:FlexibilityProvider",
    "scenario": "dt:Scenario",
    "evse": "brick:Electric_Vehicle_Charging_Station",
    # Surrogate-specific edge predicates (no semantic-graph counterpart),
    # declared by the flexibility capability. EFOnt defines neither.
    "network_impact": "flexint:hasNetworkImpact",
    "provides_flexibility": "flexint:providesFlexibility",
}


def resolve_declared_capabilities(capabilities: Iterable[str] | None) -> set[str]:
    """Return declared capability IDs, applying the legacy default.

    Args:
        capabilities: Declared IDs, or ``None`` for a caller that predates
            declared capabilities.

    Returns:
        :data:`LEGACY_DEFAULT_CAPABILITIES` for ``None``, otherwise the declared
        IDs as a set. Unknown IDs are not rejected here;
        :func:`profile_with_capabilities` rejects them by name.
    """
    if capabilities is None:
        return set(LEGACY_DEFAULT_CAPABILITIES)
    return set(capabilities)


def north_america_profile() -> dict[str, Any]:
    """Return the model-first core profile, with no capability composed over it."""
    return profile_with_capabilities(set())


_NAMESPACE_CACHE: tuple[int, int, dict[str, str]] | None = None


def _vocabulary_namespaces() -> dict[str, str]:
    """Return the cached core-plus-registered namespace map (do not mutate)."""
    global _NAMESPACE_CACHE
    registry = default_semantic_capability_registry()
    key = (id(registry), registry.revision)
    if _NAMESPACE_CACHE is None or _NAMESPACE_CACHE[:2] != key:
        merged = dict(NAMESPACES)
        for capability in registry.resolve(registry.list_ids()):
            _merge_namespaces(merged, capability.namespaces, capability.capability_id)
        _NAMESPACE_CACHE = (key[0], key[1], merged)
    return _NAMESPACE_CACHE[2]


def _all_namespaces() -> dict[str, str]:
    """Return the namespaces of the core and of every registered capability.

    This is the *spelling registry* :func:`semantic_uri` resolves against when
    it is given no namespace map -- what the network-impact surrogate and the
    record constructors use. It is deliberately wider than any one graph: the
    builder re-resolves every IRI against the active profile and refuses a
    type or predicate outside it, which is where capability scoping is
    enforced.

    Raises:
        ValueError: Two registered capabilities bind one prefix to two IRIs.
    """
    return dict(_vocabulary_namespaces())


def semantic_uri(qname: str, namespaces: Mapping[str, str] | None = None) -> str:
    """Resolve a ``prefix:name`` qname to its IRI.

    Args:
        qname: Qualified name, e.g. ``cim:ConnectivityNode``.
        namespaces: Namespace map to resolve against; defaults to the
            vocabulary-wide map of :func:`_all_namespaces`.

    Returns:
        The namespace IRI followed by the local name.

    Raises:
        ValueError: ``qname`` carries no prefix.
        KeyError: The prefix is not bound in ``namespaces``.
    """
    prefix, separator, local_name = qname.partition(":")
    if not separator:
        raise ValueError(
            f"semantic qname {qname!r} has no namespace prefix "
            "(expected '<prefix>:<name>')"
        )
    resolved = _vocabulary_namespaces() if namespaces is None else namespaces
    if prefix not in resolved:
        raise KeyError(
            f"semantic qname {qname!r} uses unbound namespace {prefix!r} "
            f"(bound: {', '.join(sorted(resolved))})"
        )
    return f"{resolved[prefix]}{local_name}"


def resolve_ingest_iri(iri: str) -> str:
    """Return the ``cim:`` qname for a CIM IRI another tool wrote.

    Args:
        iri: A full IRI in the primary CIM namespace or an ingest alias.

    Returns:
        The ``cim:<LocalName>`` qname gridalyn emits for it.

    Raises:
        ValueError: The IRI is in no CIM namespace gridalyn reads, or it is in
            an ingest alias but names a term not mapped from it.
    """
    primary = NAMESPACES["cim"]
    if iri.startswith(primary):
        return f"cim:{iri[len(primary):]}"
    for namespace in CIM_INGEST_NAMESPACES:
        if iri.startswith(namespace):
            local_name = iri[len(namespace) :]
            if local_name in CIM_INGEST_TERMS:
                return f"cim:{local_name}"
            raise ValueError(
                f"{iri} is in the CIM ingest namespace {namespace}, but "
                f"{local_name!r} is not mapped from it (mapped: "
                f"{', '.join(sorted(CIM_INGEST_TERMS))}); CIM18 renamed classes, "
                "so map the term explicitly rather than by name"
            )
    raise ValueError(
        f"{iri} is in no CIM namespace gridalyn reads (primary: {primary}; "
        f"ingest: {', '.join(CIM_INGEST_NAMESPACES)})"
    )


def resolve_deprecated_term(qname: str) -> TermAlias | None:
    """Return the alias a deprecated qname resolves through, or ``None``.

    Searches every registered capability, not only the ones a graph declares:
    a query against an old graph must resolve whichever capability wrote it.

    Args:
        qname: A type or predicate qname, e.g. ``cls:SoftCLSContract``.

    Returns:
        The declared :class:`TermAlias`, or ``None`` when ``qname`` is current
        or unknown.
    """
    registry = default_semantic_capability_registry()
    for capability in registry.resolve(registry.list_ids()):
        for alias in capability.deprecated_aliases:
            if alias.deprecated == qname:
                return alias
    return None


def _merge_namespaces(
    target: dict[str, str], additions: Mapping[str, str], owner: str
) -> None:
    """Bind ``additions`` into ``target``, refusing to rebind a prefix."""
    for prefix, iri in additions.items():
        existing = target.get(prefix)
        if existing is not None and existing != iri:
            raise ValueError(
                f"semantic capability {owner!r} binds namespace prefix {prefix!r} "
                f"to {iri}, but it is already bound to {existing}; one prefix "
                "names one IRI"
            )
        target[prefix] = iri


def _merge_standards(
    target: dict[str, list[str]],
    additions: Mapping[str, tuple[str, ...]],
    owner: str,
) -> None:
    """Add a capability's primary standards, refusing to redeclare a concern."""
    for concern, standards in additions.items():
        if concern in target:
            raise ValueError(
                f"semantic capability {owner!r} redeclares primary standard "
                f"{concern!r} (already: {', '.join(target[concern])})"
            )
        target[concern] = list(standards)


def _merge_relationship(
    existing: RelationshipSpec | None,
    addition: RelationshipSpec,
    declared_by: list[str],
    owner: str,
) -> RelationshipSpec:
    """Extend a relationship with a second declaration of the same predicate.

    Raises:
        ValueError: The declarations name different predicates or different
            cardinalities -- one relationship type maps to one predicate.
    """
    if existing is None:
        return addition
    if existing.predicate != addition.predicate:
        raise ValueError(
            f"relationship {addition.name} is declared with two predicates: "
            f"{existing.predicate} by {', '.join(declared_by)} and "
            f"{addition.predicate} by {owner}; one relationship type must map "
            "to one predicate"
        )
    if (
        existing.source_cardinality
        and addition.source_cardinality
        and existing.source_cardinality != addition.source_cardinality
    ):
        raise ValueError(
            f"relationship {addition.name} is declared with two cardinalities: "
            f"{existing.source_cardinality} by {', '.join(declared_by)} and "
            f"{addition.source_cardinality} by {owner}"
        )
    return RelationshipSpec(
        name=existing.name,
        predicate=existing.predicate,
        domain=tuple(sorted({*existing.domain, *addition.domain})),
        range=tuple(sorted({*existing.range, *addition.range})),
        source_cardinality=existing.source_cardinality or addition.source_cardinality,
        note=existing.note or addition.note,
    )


def _compose_relationships(
    active: tuple[SemanticCapability, ...],
) -> tuple[dict[str, RelationshipSpec], dict[str, list[str]]]:
    """Compose the core relationships with every active capability's."""
    relationships = {spec.name: spec for spec in CORE_RELATIONSHIPS}
    declared_by = {spec.name: ["core"] for spec in CORE_RELATIONSHIPS}
    for capability in active:
        for spec in capability.relationships:
            owners = declared_by.setdefault(spec.name, [])
            relationships[spec.name] = _merge_relationship(
                relationships.get(spec.name), spec, owners, capability.capability_id
            )
            owners.append(capability.capability_id)
    return relationships, declared_by


def _compose_scenario_counts(
    active: tuple[SemanticCapability, ...],
) -> dict[str, ScenarioCountRule]:
    """Collect the active capabilities' count rules, refusing a duplicate key."""
    rules: dict[str, ScenarioCountRule] = {}
    for capability in active:
        for rule in capability.scenario_counts:
            if rule.key in rules:
                raise ValueError(
                    f"scenario count {rule.key!r} is declared twice (again by "
                    f"{capability.capability_id!r})"
                )
            rules[rule.key] = rule
    return rules


def _compose_aliases(
    active: tuple[SemanticCapability, ...],
) -> dict[str, tuple[TermAlias, str]]:
    """Collect the active capabilities' deprecated aliases with their declarers."""
    aliases: dict[str, tuple[TermAlias, str]] = {}
    for capability in active:
        for alias in capability.deprecated_aliases:
            if alias.deprecated in aliases:
                raise ValueError(
                    f"deprecated term {alias.deprecated} is aliased twice (again by "
                    f"{capability.capability_id!r})"
                )
            aliases[alias.deprecated] = (alias, capability.capability_id)
    return aliases


def _check_vocabulary(
    types: set[str],
    relationships: Mapping[str, RelationshipSpec],
    rules: Mapping[str, ScenarioCountRule],
    namespaces: Mapping[str, str],
    predicates: set[str],
) -> None:
    """Refuse a composed profile whose declarations reference undeclared names."""
    bound = ", ".join(sorted(namespaces))
    for qname in sorted(types | predicates):
        if qname.partition(":")[0] not in namespaces:
            raise ValueError(
                f"{qname} uses a namespace no active declaration binds (bound: {bound})"
            )
    for spec in relationships.values():
        undeclared = sorted({*spec.domain, *spec.range} - types)
        if undeclared:
            raise ValueError(
                f"relationship {spec.name} names {', '.join(undeclared)} in its "
                "domain or range, which no active declaration lists as a "
                "semantic type"
            )
    for rule in rules.values():
        if rule.semantic_type not in types:
            raise ValueError(
                f"scenario count {rule.key!r} counts {rule.semantic_type}, which "
                "no active declaration lists as a semantic type"
            )


def _check_aliases(
    aliases: Mapping[str, tuple[TermAlias, str]],
    types: set[str],
    predicates: set[str],
) -> None:
    """Refuse an alias to an undeclared term, or an alias of a term still live."""
    live = types | predicates
    for deprecated, (alias, _declarer) in sorted(aliases.items()):
        if alias.replacement not in live:
            raise ValueError(
                f"deprecated term {deprecated} is aliased to {alias.replacement}, "
                "which no active declaration lists as a semantic type or predicate"
            )
        if deprecated in live:
            raise ValueError(
                f"deprecated term {deprecated} is still declared as a live term; a "
                "term is either current or an alias, not both"
            )


def _relationship_payload(
    spec: RelationshipSpec, namespaces: Mapping[str, str], declared_by: list[str]
) -> dict[str, Any]:
    """Render one composed relationship as JSON-native profile data."""
    return {
        "predicate": spec.predicate,
        "iri": semantic_uri(spec.predicate, namespaces),
        "domain": list(spec.domain),
        "range": list(spec.range),
        "source_cardinality": (
            list(spec.source_cardinality) if spec.source_cardinality else None
        ),
        "declared_by": list(declared_by),
        "note": spec.note or None,
    }


def profile_with_capabilities(
    capabilities: Iterable[str] | None = None,
    *,
    registry: SemanticCapabilityRegistry | None = None,
) -> dict[str, Any]:
    """Compose the semantic profile for a set of declared capabilities.

    Args:
        capabilities: Declared capability IDs. ``None`` applies
            :data:`LEGACY_DEFAULT_CAPABILITIES`; an explicit set composes the
            model-first core plus exactly those capabilities.
        registry: Registry to resolve against; defaults to the shared default.

    Returns:
        A JSON-native profile: namespaces, types, and for every relationship
        its one predicate, IRI, domain, range, cardinality and declarers; plus
        the scenario count rules the validator may apply.

    Raises:
        UnknownSemanticCapabilityError: A declared capability is not registered.
        ValueError: The declarations conflict (a prefix bound to two IRIs, a
            relationship with two predicates or cardinalities, a count rule
            declared twice) or reference an undeclared type or namespace.
    """
    declared = resolve_declared_capabilities(capabilities)
    active: tuple[SemanticCapability, ...] = ()
    if declared:
        active = (registry or default_semantic_capability_registry()).resolve(declared)
    namespaces = dict(NAMESPACES)
    standards = {concern: list(names) for concern, names in PRIMARY_STANDARDS.items()}
    types = set(CORE_SEMANTIC_TYPES)
    extra_predicates: set[str] = set()
    for capability in active:
        _merge_namespaces(namespaces, capability.namespaces, capability.capability_id)
        _merge_standards(
            standards, capability.primary_standards, capability.capability_id
        )
        types.update(capability.semantic_types)
        extra_predicates.update(capability.predicates)
    relationships, declared_by = _compose_relationships(active)
    rules = _compose_scenario_counts(active)
    aliases = _compose_aliases(active)
    predicates = extra_predicates | {spec.predicate for spec in relationships.values()}
    _check_vocabulary(types, relationships, rules, namespaces, predicates)
    _check_aliases(aliases, types, predicates)
    return {
        "semantic_profile": "north_america",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "capabilities": sorted(declared),
        "namespaces": namespaces,
        "primary_standards": standards,
        "allowed_semantic_types": sorted(types),
        "relationship_types": sorted(relationships),
        "relationships": {
            name: _relationship_payload(
                relationships[name], namespaces, declared_by[name]
            )
            for name in sorted(relationships)
        },
        "predicates": sorted(extra_predicates),
        "scenario_counts": {
            key: {
                "semantic_type": rules[key].semantic_type,
                "property_true": rules[key].property_true,
                "property_equals": dict(rules[key].property_equals),
            }
            for key in sorted(rules)
        },
        "deprecated_aliases": {
            name: {
                "replacement": alias.replacement,
                "properties": dict(alias.properties),
                "note": alias.note or None,
                "declared_by": declarer,
            }
            for name, (alias, declarer) in sorted(aliases.items())
        },
        "ingest_namespaces": {"cim": list(CIM_INGEST_NAMESPACES)},
        "unit_conventions": dict(UNIT_CONVENTIONS),
    }


def write_profile(
    path: Path,
    capabilities: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Write the composed North America profile and return it.

    Args:
        path: Destination for the profile JSON.
        capabilities: Declared semantic capabilities (see
            :func:`profile_with_capabilities`).

    Returns:
        The written profile dict.
    """
    profile = profile_with_capabilities(capabilities)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(profile, f, indent=2, sort_keys=True)
    return profile


__all__ = [
    "CIM_INGEST_NAMESPACES",
    "CIM_INGEST_TERMS",
    "CORE_RELATIONSHIPS",
    "CORE_SEMANTIC_TYPES",
    "DEPRECATED_NAMESPACES",
    "GRIDALYN_ONTOLOGY_BASE",
    "LEGACY_DEFAULT_CAPABILITIES",
    "NAMESPACES",
    "RELATIONSHIP_TYPES",
    "SEMANTIC_PROFILE_IDS",
    "SEMANTIC_TYPE",
    "SemanticProfileId",
    "north_america_profile",
    "profile_with_capabilities",
    "resolve_declared_capabilities",
    "resolve_deprecated_term",
    "resolve_ingest_iri",
    "semantic_uri",
    "write_profile",
]
