"""Accumulator that owns semantic-graph node and edge identity, once.

Before this module, ``build_semantic_graph`` deduplicated three different ways
inside one 822-line function:

* topology, premises, scenarios and the asset registry appended bare, relying
  on a closing ``drop_duplicates("node_id")`` that keeps the FIRST row and
  therefore discards a later row's differing ``properties`` in silence;
* the provider-registry section used ``_append_unique_node`` against a
  ``seen_nodes`` set built *partway through* the function, so the set could not
  see anything appended before it was constructed, and nothing appended after
  it by the other mechanism;
* edges used a third set, threaded through every call by hand.

Measured on the shipped twin (74 286 nodes, 147 065 edges) the three agree:
there are zero duplicate IDs, so nothing is being lost today. The hazard is
that they *could* disagree, silently, the first time two source tables mint the
same ID with different payloads -- and which of the three a new emitter happens
to use would decide whether that loss is caught. One accumulator with one rule
removes the question.

The rule is first-write-wins, matching the previous ``drop_duplicates``
semantics exactly.

**The profile is enforced on arrival (2026-09-10).** Given the profile a graph
is built against, the builder refuses a node whose semantic type the profile
does not declare, and an edge whose relationship it does not declare or whose
predicate is not that relationship's one declared predicate; and it resolves
every IRI against the profile's own namespaces. An emitter bug
therefore fails the build at the record that caused it. Without a profile the
builder owns identity only, as before.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from gridalyn.twin.semantic.profile import semantic_uri


class SemanticGraphBuilder:
    """Collect nodes and edges, resolving identity collisions on arrival."""

    def __init__(self, profile: Mapping[str, Any] | None = None) -> None:
        """Start empty, optionally holding every record to a profile.

        Args:
            profile: A profile from
                :func:`~gridalyn.twin.semantic.profile.profile_with_capabilities`.
                ``None`` enforces identity only.
        """
        self._nodes: list[dict[str, Any]] = []
        self._edges: list[dict[str, Any]] = []
        self._node_ids: set[str] = set()
        self._edge_ids: set[str] = set()
        self._namespaces: dict[str, str] | None = None
        self._types: frozenset[str] | None = None
        self._relationships: dict[str, Mapping[str, Any]] | None = None
        self._capabilities: tuple[str, ...] = ()
        if profile is not None:
            self._namespaces = dict(profile["namespaces"])
            self._types = frozenset(profile["allowed_semantic_types"])
            relationships = profile.get("relationships")
            if relationships is not None:
                self._relationships = dict(relationships)
            self._capabilities = tuple(profile.get("capabilities", ()))

    def add_node(self, node: dict[str, Any]) -> bool:
        """Add a node unless its ``node_id`` was already taken.

        Args:
            node: A node record from :func:`~gridalyn.twin.semantic.records._node`.

        Returns:
            True when the node was added, False when its ID was already
            present. First write wins, matching the ``drop_duplicates`` this
            replaces; the return value lets an emitter notice a collision it
            did not expect rather than only ever discovering it downstream.

        Raises:
            ValueError: The builder holds a profile that does not declare the
                node's semantic type.
            KeyError: Without a profile, the node's type uses an unbound prefix.
        """
        node = self._resolve_node(node)
        node_id = node["node_id"]
        if node_id in self._node_ids:
            return False
        self._node_ids.add(node_id)
        self._nodes.append(node)
        return True

    def add_edge(self, edge: dict[str, Any]) -> bool:
        """Add an edge unless its ``edge_id`` was already taken.

        Args:
            edge: An edge record from :func:`~gridalyn.twin.semantic.records._edge`.

        Returns:
            True when the edge was added, False when its ID was already
            present.

        Raises:
            ValueError: The builder holds a profile that does not declare the
                edge's relationship, or declares a different predicate for it.
            KeyError: Without a profile, the predicate uses an unbound prefix.
        """
        edge = self._resolve_edge(edge)
        edge_id = edge["edge_id"]
        if edge_id in self._edge_ids:
            return False
        self._edge_ids.add(edge_id)
        self._edges.append(edge)
        return True

    def _describe_capabilities(self) -> str:
        return ", ".join(self._capabilities) or "none"

    def _resolve_node(self, node: dict[str, Any]) -> dict[str, Any]:
        semantic_type = str(node["semantic_type"])
        if self._types is None:
            if "://" in str(node["semantic_uri"]):
                return node
            return {**node, "semantic_uri": semantic_uri(semantic_type)}
        if semantic_type not in self._types:
            raise ValueError(
                f"node {node['node_id']!r} has semantic type {semantic_type!r}, "
                "which the active profile does not declare (capabilities: "
                f"{self._describe_capabilities()}); declare the capability that "
                "owns the type"
            )
        return {**node, "semantic_uri": semantic_uri(semantic_type, self._namespaces)}

    def _resolve_edge(self, edge: dict[str, Any]) -> dict[str, Any]:
        emitted = str(edge["semantic_uri"])
        if self._relationships is None:
            if "://" in emitted:
                return edge
            return {**edge, "semantic_uri": semantic_uri(emitted)}
        relationship = str(edge["relationship_type"])
        declared = self._relationships.get(relationship)
        if declared is None:
            raise ValueError(
                f"edge {edge['edge_id']!r} uses relationship {relationship!r}, "
                "which the active profile does not declare (capabilities: "
                f"{self._describe_capabilities()}; declared: "
                f"{', '.join(sorted(self._relationships)) or 'none'})"
            )
        if emitted not in (declared["iri"], declared["predicate"]):
            raise ValueError(
                f"edge {edge['edge_id']!r}: relationship {relationship!r} was "
                f"emitted with predicate {emitted!r}, but the profile declares "
                f"{declared['predicate']} ({declared['iri']}); one relationship "
                "type maps to one predicate"
            )
        return {**edge, "semantic_uri": declared["iri"]}

    @property
    def node_count(self) -> int:
        """Return how many distinct nodes have been collected."""
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        """Return how many distinct edges have been collected."""
        return len(self._edges)

    def to_frames(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Return the collected graph as sorted node and edge frames.

        Returns:
            ``(nodes, edges)`` sorted by ID with a reset index. Sorting makes
            emitter call order irrelevant to the emitted artifact.
        """
        nodes = pd.DataFrame(self._nodes).sort_values("node_id").reset_index(drop=True)
        edges = pd.DataFrame(self._edges).sort_values("edge_id").reset_index(drop=True)
        return nodes, edges


__all__ = ["SemanticGraphBuilder"]
