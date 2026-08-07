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
        for start in range(0, len(self.nodes), batch_size):
            chunk = self.nodes.iloc[start : start + batch_size]
            labels = sorted({_cypher_label(value) for value in chunk["semantic_type"]})
            cypher = (
                "UNWIND $props AS p\n"
                "MERGE (n:SemanticAsset {node_id: p.node_id})\n"
                "SET n += p"
            )
            node_batches.append(
                {
                    "cypher": cypher,
                    "params": {"props": chunk.to_dict("records")},
                    "labels": labels,
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
