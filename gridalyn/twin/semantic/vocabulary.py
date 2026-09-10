"""What a semantic capability declares, as data.

A capability used to be a hardcoded ``if "flexibility" in capabilities`` in
three modules; its relationships were a list of names; and each relationship's
predicate IRI was whatever string the emitter that produced the edge happened
to pass. Measured on the shipped twin (74 286 nodes, 147 065 edges, 2026-09-10):
``ENABLES`` carried two IRIs, ``HAS_FLEXIBILITY_RESOURCE`` two, and the 10 357
topology edges used the *class* ``cim:ConnectivityNode`` as their predicate.
Nothing could catch any of it, because nothing declared what the predicate
should be.

These dataclasses are that declaration. A relationship names one predicate, the
semantic types it may start and end at, and optionally how many such edges each
node of a domain type must carry.
:func:`gridalyn.twin.semantic.profile.profile_with_capabilities` composes them
-- refusing a second predicate for one relationship -- and both
:class:`~gridalyn.twin.semantic.builder.SemanticGraphBuilder` and
:func:`~gridalyn.twin.semantic.validation.validate_semantic_graph` hold a graph
to the result.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    import pandas as pd

    from gridalyn.twin.semantic.builder import SemanticGraphBuilder


@dataclass(frozen=True)
class RelationshipSpec:
    """One relationship type and the axioms its edges are held to.

    Attributes:
        name: The ``relationship_type`` label edges carry, e.g. ``HAS_LOAD``.
        predicate: The one predicate qname every such edge resolves to.
        domain: Semantic types an edge of this relationship may start at.
        range: Semantic types an edge of this relationship may end at.
        source_cardinality: ``(min, max)`` edges of this relationship every
            node of a domain type must originate, or ``None`` when the number
            is unconstrained.
        note: Why the predicate is what it is, when that is not self-evident.
    """

    name: str
    predicate: str
    domain: tuple[str, ...]
    range: tuple[str, ...]
    source_cardinality: tuple[int, int] | None = None
    note: str = ""


@dataclass(frozen=True)
class ScenarioCountRule:
    """How to count one per-scenario quantity a scenario registry states.

    Attributes:
        key: The quantity's name in the scenario summary, e.g. ``n_ev``.
        semantic_type: Nodes of this type within the scenario are counted.
        property_true: When set, only nodes whose JSON ``properties`` hold a
            truthy value under this key are counted.
    """

    key: str
    semantic_type: str
    property_true: str | None = None


@dataclass(frozen=True)
class CapabilityInputs:
    """The canonical twin tables a capability's extender may read.

    Attributes:
        buses: ``grid_buses`` table.
        lines: ``grid_lines`` table.
        transformers: ``grid_transformers`` table.
        buildings: ``buildings`` table.
        connectivity: ``building_grid_connectivity`` table.
        asset_registry: Scenario asset registry; empty when absent.
        provider_registry: Flexibility provider registry; empty when absent.
        timeseries_manifests: Run manifests keyed by name.
    """

    buses: pd.DataFrame
    lines: pd.DataFrame
    transformers: pd.DataFrame
    buildings: pd.DataFrame
    connectivity: pd.DataFrame
    asset_registry: pd.DataFrame
    provider_registry: pd.DataFrame
    timeseries_manifests: Mapping[str, Any]


class GraphExtender(Protocol):
    """Emits a capability's nodes and edges into a graph under construction."""

    def __call__(self, builder: SemanticGraphBuilder, inputs: CapabilityInputs) -> None:
        """Add the capability's records to ``builder``, reading ``inputs``."""


@dataclass(frozen=True)
class SemanticCapability:
    """An on-demand semantic layer: its vocabulary, its axioms, its emitter.

    Attributes:
        capability_id: Explicit ID a project declares, e.g. ``flexibility``.
        namespaces: Prefixes the capability binds, beyond the core's.
        primary_standards: Standards the capability claims, by concern.
        semantic_types: Node types the capability adds to the profile.
        relationships: Relationships the capability declares or extends. A
            relationship already declared elsewhere may be extended (its
            domain and range are unioned) only with the same predicate.
        scenario_counts: Per-scenario count rules the validator can apply.
        extend: Emits the capability's records into a graph, or ``None`` for
            a vocabulary-only capability.
    """

    capability_id: str
    namespaces: Mapping[str, str]
    primary_standards: Mapping[str, tuple[str, ...]]
    semantic_types: tuple[str, ...]
    relationships: tuple[RelationshipSpec, ...]
    scenario_counts: tuple[ScenarioCountRule, ...] = ()
    extend: GraphExtender | None = None


__all__ = [
    "CapabilityInputs",
    "GraphExtender",
    "RelationshipSpec",
    "ScenarioCountRule",
    "SemanticCapability",
]
