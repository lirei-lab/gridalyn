"""Validation utilities for the federated semantic digital-twin graph."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


def _loads_json(value: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    return json.loads(value)


def _scenario_count(nodes: pd.DataFrame, scenario_id: str, semantic_type: str) -> int:
    return int(
        (
            (nodes["scenario_id"].fillna("") == scenario_id)
            & (nodes["semantic_type"] == semantic_type)
        ).sum()
    )


def _hard_preferred_count(nodes: pd.DataFrame, scenario_id: str) -> int:
    hard = nodes.loc[
        (nodes["scenario_id"].fillna("") == scenario_id)
        & (nodes["semantic_type"] == "cls:HardCLSContract")
    ]
    return int(
        sum(bool(_loads_json(row["properties"]).get("hard_preferred")) for _, row in hard.iterrows())
    )


def validate_semantic_graph(
    nodes: pd.DataFrame,
    edges: pd.DataFrame,
    profile: dict[str, Any],
    expected_scenario_counts: dict[str, dict[str, int]] | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    expected_scenario_counts = expected_scenario_counts or {}
    namespaces = profile.get("namespaces", {})
    allowed_types = set(profile.get("allowed_semantic_types", []))
    allowed_relationships = set(profile.get("relationship_types", []))

    required_node_cols = {
        "node_id",
        "labels",
        "semantic_type",
        "semantic_uri",
        "source_standard",
        "source_table",
        "source_id",
        "name",
        "scenario_id",
        "properties",
    }
    required_edge_cols = {
        "edge_id",
        "source_id",
        "target_id",
        "relationship_type",
        "semantic_uri",
        "source_standard",
        "source_table",
        "scenario_id",
        "properties",
    }
    if missing := sorted(required_node_cols - set(nodes.columns)):
        errors.append(f"nodes missing columns: {', '.join(missing)}")
    if missing := sorted(required_edge_cols - set(edges.columns)):
        errors.append(f"edges missing columns: {', '.join(missing)}")
    if errors:
        return _report(nodes, edges, errors, warnings)

    if nodes["node_id"].duplicated().any():
        errors.append("duplicate node_id values found")
    if edges["edge_id"].duplicated().any():
        errors.append("duplicate edge_id values found")

    node_ids = set(nodes["node_id"])
    for _, edge in edges.iterrows():
        if edge["source_id"] not in node_ids or edge["target_id"] not in node_ids:
            errors.append(
                f"edge {edge['edge_id']} has missing endpoint "
                f"{edge['source_id']} -> {edge['target_id']}"
            )

    for semantic_type in nodes["semantic_type"].dropna().unique():
        if ":" not in semantic_type:
            errors.append(f"semantic type lacks namespace: {semantic_type}")
            continue
        prefix = semantic_type.split(":", 1)[0]
        if prefix not in namespaces:
            errors.append(f"semantic type uses unknown namespace: {semantic_type}")
        if allowed_types and semantic_type not in allowed_types:
            warnings.append(f"semantic type not listed in profile: {semantic_type}")

    for rel in edges["relationship_type"].dropna().unique():
        if allowed_relationships and rel not in allowed_relationships:
            errors.append(f"relationship type not listed in profile: {rel}")

    has_load = edges.loc[edges["relationship_type"] == "HAS_LOAD"]
    building_ids = set(nodes.loc[nodes["semantic_type"] == "brick:Building", "node_id"])
    has_load_counts = has_load.groupby("source_id").size().to_dict()
    for building_id in building_ids:
        if has_load_counts.get(building_id, 0) != 1:
            errors.append(f"building {building_id} must have exactly one HAS_LOAD edge")

    connected = edges.loc[edges["relationship_type"] == "CONNECTED_TO"]
    load_ids = set(nodes.loc[nodes["semantic_type"] == "cim:EnergyConsumer", "node_id"])
    connected_counts = connected.groupby("source_id").size().to_dict()
    for load_id in load_ids:
        if connected_counts.get(load_id, 0) != 1:
            errors.append(f"load {load_id} must have exactly one CONNECTED_TO edge")

    for scenario_id, expected in expected_scenario_counts.items():
        actual_ev = _scenario_count(nodes, scenario_id, "ieee2030_5:EVSE")
        actual_soft = _scenario_count(nodes, scenario_id, "cls:SoftCLSContract")
        actual_hard_preferred = _hard_preferred_count(nodes, scenario_id)
        expected_map = {
            "n_ev": actual_ev,
            "n_soft_participants": actual_soft,
            "n_hard_preferred": actual_hard_preferred,
        }
        for key, actual in expected_map.items():
            if key in expected and expected[key] != actual:
                errors.append(
                    f"scenario {scenario_id} {key} expected {expected[key]} got {actual}"
                )

    for _, node in nodes.iterrows():
        props = _loads_json(node["properties"])
        for key in props:
            if key.endswith(("power", "voltage", "current")):
                errors.append(f"property {key} on {node['node_id']} lacks explicit unit")

    return _report(nodes, edges, errors, warnings)


def write_validation_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(report, f, indent=2, sort_keys=True)


def _report(nodes: pd.DataFrame, edges: pd.DataFrame, errors: list[str], warnings: list[str]) -> dict[str, Any]:
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "valid": len(errors) == 0,
        "node_count": int(len(nodes)),
        "edge_count": int(len(edges)),
        "error_count": int(len(errors)),
        "warning_count": int(len(warnings)),
        "errors": errors,
        "warnings": warnings,
    }
