"""Record constructors for semantic-graph nodes and edges.

Split out of ``mappings.py`` so the emitters and the orchestrator can share
them without importing each other. Pure construction: no accumulation, no
identity -- identity belongs to
:class:`~gridalyn.twin.semantic.builder.SemanticGraphBuilder`.
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from gridalyn.twin.semantic.profile import semantic_uri


def _clean_value(value: Any) -> Any:
    if pd.isna(value) if not isinstance(value, (list, tuple, dict)) else False:
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _json_properties(values: dict[str, Any]) -> str:
    clean = {key: _clean_value(value) for key, value in values.items()}
    return json.dumps(clean, sort_keys=True)


def _node(
    node_id: str,
    labels: list[str],
    semantic_type: str,
    source_standard: str,
    source_table: str,
    source_id: str,
    name: str | None = None,
    scenario_id: str | None = None,
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "labels": ";".join(labels),
        "semantic_type": semantic_type,
        "semantic_uri": semantic_uri(semantic_type),
        "source_standard": source_standard,
        "source_table": source_table,
        "source_id": source_id,
        "name": name,
        "scenario_id": scenario_id,
        "properties": _json_properties(properties or {}),
    }


def _edge(
    source_id: str,
    relationship_type: str,
    target_id: str,
    semantic_type: str,
    source_standard: str,
    source_table: str,
    source_id_value: str,
    scenario_id: str | None = None,
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    edge_id = f"{source_id}|{relationship_type}|{target_id}"
    if scenario_id:
        edge_id = f"{scenario_id}|{edge_id}"
    return {
        "edge_id": edge_id,
        "source_id": source_id,
        "target_id": target_id,
        "relationship_type": relationship_type,
        "semantic_uri": semantic_uri(semantic_type),
        "source_standard": source_standard,
        "source_table": source_table,
        "scenario_id": scenario_id,
        "properties": _json_properties(properties or {"source_id": source_id_value}),
    }


def _safe_str(value: Any) -> str | None:
    value = _clean_value(value)
    return None if value is None else str(value)


def _split_semicolon_values(value: Any) -> list[str]:
    value = _safe_str(value)
    if not value:
        return []
    return [part for part in value.split(";") if part]


__all__ = [
    "_clean_value",
    "_edge",
    "_json_properties",
    "_node",
    "_safe_str",
    "_split_semicolon_values",
]
