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
semantics exactly, so the emitted graph is unchanged.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


class SemanticGraphBuilder:
    """Collect nodes and edges, resolving identity collisions on arrival."""

    def __init__(self) -> None:
        """Start empty, with the identity sets the accumulator owns."""
        self._nodes: list[dict[str, Any]] = []
        self._edges: list[dict[str, Any]] = []
        self._node_ids: set[str] = set()
        self._edge_ids: set[str] = set()

    def add_node(self, node: dict[str, Any]) -> bool:
        """Add a node unless its ``node_id`` was already taken.

        Args:
            node: A node record from :func:`~gridalyn.twin.semantic.mappings._node`.

        Returns:
            True when the node was added, False when its ID was already
            present. First write wins, matching the ``drop_duplicates`` this
            replaces; the return value lets an emitter notice a collision it
            did not expect rather than only ever discovering it downstream.
        """
        node_id = node["node_id"]
        if node_id in self._node_ids:
            return False
        self._node_ids.add(node_id)
        self._nodes.append(node)
        return True

    def add_edge(self, edge: dict[str, Any]) -> bool:
        """Add an edge unless its ``edge_id`` was already taken.

        Args:
            edge: An edge record from :func:`~gridalyn.twin.semantic.mappings._edge`.

        Returns:
            True when the edge was added, False when its ID was already
            present.
        """
        edge_id = edge["edge_id"]
        if edge_id in self._edge_ids:
            return False
        self._edge_ids.add(edge_id)
        self._edges.append(edge)
        return True

    def has_node(self, node_id: str) -> bool:
        """Report whether a node ID has already been minted.

        Args:
            node_id: The ID to test.

        Returns:
            True when some emitter already added it.
        """
        return node_id in self._node_ids

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
            emitter call order irrelevant to the emitted artifact, which is why
            unifying the three dedup mechanisms cannot move a row.
        """
        nodes = pd.DataFrame(self._nodes).sort_values("node_id").reset_index(drop=True)
        edges = pd.DataFrame(self._edges).sort_values("edge_id").reset_index(drop=True)
        return nodes, edges


__all__ = ["SemanticGraphBuilder"]
