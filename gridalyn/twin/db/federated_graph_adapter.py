"""Backend-neutral adapter for the federated semantic graph artifacts.

This adapter GENERATES Cypher batches (``to_falkor_batches``) for migrating the
semantic graph (``nodes.parquet`` / ``edges.parquet``) into FalkorDB-compatible
stores. It does NOT connect to, load, or query a FalkorDB server, and requires
no graph-database runtime (Phase 9, 2026-08-07).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


def _cypher_label(semantic_type: str) -> str:
    local = semantic_type.split(":", 1)[-1]
    label = re.sub(r"[^A-Za-z0-9_]", "_", local)
    if not label or label[0].isdigit():
        label = f"Semantic_{label}"
    return label


def _node_labels(semantic_type: Any, labels: Any) -> tuple[str, ...]:
    """Return the sorted, deduplicated Cypher labels for one node.

    Combines the type-derived label with the node's own ``labels`` column
    (``;``-joined), so a node's MERGE carries every label the semantic graph
    recorded for it, not just the one derived from its primary type.

    Args:
        semantic_type: The node's ``semantic_type`` value.
        labels: The node's ``labels`` value (``;``-joined string, or absent).

    Returns:
        Sorted, deduplicated Cypher-safe label names.

    Raises:
        ValueError: If ``semantic_type`` is missing -- a node with no type
            has no label to MERGE on, and silently coercing it would export
            an anonymous node no query could ever select.
    """
    if not isinstance(semantic_type, str) or not semantic_type:
        raise ValueError(
            f"to_falkor_batches: a node has semantic_type={semantic_type!r}; "
            "every exported node must declare one -- run "
            "`gridalyn semantic validate` on the source parquet first"
        )
    names = {_cypher_label(semantic_type)}
    if isinstance(labels, str) and labels:
        names |= {_cypher_label(part) for part in labels.split(";") if part}
    return tuple(sorted(names))


@dataclass
class FederatedGraphAdapter:
    nodes: pd.DataFrame
    edges: pd.DataFrame

    @classmethod
    def from_parquet(cls, semantic_dir: str | Path) -> "FederatedGraphAdapter":
        semantic_path = Path(semantic_dir)
        return cls(
            nodes=pd.read_parquet(semantic_path / "nodes.parquet"),
            edges=pd.read_parquet(semantic_path / "edges.parquet"),
        )

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        matches = self.nodes.loc[self.nodes["node_id"] == node_id]
        if matches.empty:
            return None
        return matches.iloc[0].to_dict()

    def neighbors(
        self, node_id: str, relationship_type: str | None = None
    ) -> list[str]:
        edges = self.edges.loc[self.edges["source_id"] == node_id]
        if relationship_type is not None:
            edges = edges.loc[edges["relationship_type"] == relationship_type]
        return edges["target_id"].tolist()

    def to_falkor_batches(
        self, batch_size: int = 500
    ) -> dict[str, list[dict[str, Any]]]:
        node_batches: list[dict[str, Any]] = []
        edge_batches: list[dict[str, Any]] = []
        label_column = self.nodes["labels"] if "labels" in self.nodes.columns else None
        node_labels = pd.Series(
            [
                _node_labels(
                    semantic_type,
                    None if label_column is None else label_column.iat[position],
                )
                for position, semantic_type in enumerate(self.nodes["semantic_type"])
            ],
            index=self.nodes.index,
            dtype=object,
        )
        for labels, group_index in sorted(
            node_labels.groupby(node_labels).groups.items()
        ):
            group = self.nodes.loc[group_index]
            for start in range(0, len(group), batch_size):
                chunk = group.iloc[start : start + batch_size]
                label_clause = ":".join(("SemanticAsset", *labels))
                cypher = (
                    "UNWIND $props AS p\n"
                    f"MERGE (n:{label_clause} {{node_id: p.node_id}})\n"
                    "SET n += p"
                )
                node_batches.append(
                    {
                        "cypher": cypher,
                        "params": {"props": chunk.to_dict("records")},
                        "labels": list(labels),
                    }
                )

        for start in range(0, len(self.edges), batch_size):
            chunk = self.edges.iloc[start : start + batch_size]
            cypher = (
                "UNWIND $props AS e\n"
                "MATCH (source:SemanticAsset {node_id: e.source_id})\n"
                "MATCH (target:SemanticAsset {node_id: e.target_id})\n"
                "MERGE (source)-[r:SEMANTIC_RELATION {edge_id: e.edge_id}]->(target)\n"
                "SET r += e"
            )
            edge_batches.append(
                {
                    "cypher": cypher,
                    "params": {"props": chunk.to_dict("records")},
                }
            )
        return {"nodes": node_batches, "edges": edge_batches}
