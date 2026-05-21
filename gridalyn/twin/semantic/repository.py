"""Query API for materialized semantic graph artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


def _loads_json(value: str | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    return json.loads(value)


@dataclass(frozen=True)
class SemanticGraphRepository:
    """Read and query Gridalyn semantic graph node and edge tables."""

    nodes: pd.DataFrame
    edges: pd.DataFrame

    @classmethod
    def from_parquet(cls, semantic_dir: str | Path) -> "SemanticGraphRepository":
        semantic_path = Path(semantic_dir)
        return cls(
            nodes=pd.read_parquet(semantic_path / "nodes.parquet"),
            edges=pd.read_parquet(semantic_path / "edges.parquet"),
        )

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        """Return one node as a dict with parsed properties."""
        matches = self.nodes.loc[self.nodes["node_id"] == node_id]
        if matches.empty:
            return None
        return self._node_record(matches.iloc[0])

    def neighbors(
        self,
        node_id: str,
        relationship_type: str | None = None,
        *,
        direction: str = "out",
        scenario_id: str | None = None,
    ) -> tuple[str, ...]:
        """Return neighboring node IDs for a relationship direction."""
        matches = self._matching_edges(
            node_id,
            relationship_type,
            direction=direction,
            scenario_id=scenario_id,
        )
        column = "target_id" if direction == "out" else "source_id"
        return tuple(matches[column].dropna().astype(str).drop_duplicates().tolist())

    def get_asset_context(self, node_id: str) -> dict[str, Any]:
        """Return a node plus grouped incoming and outgoing relationships."""
        node = self.get_node(node_id)
        if node is None:
            raise KeyError(f"Semantic node not found: {node_id}")
        outgoing = self._group_neighbors(self.edges.loc[self.edges["source_id"] == node_id], "target_id")
        incoming = self._group_neighbors(self.edges.loc[self.edges["target_id"] == node_id], "source_id")
        return {"node": node, "outgoing": outgoing, "incoming": incoming}

    def assets_in_scenario(
        self,
        scenario_id: str,
        semantic_type: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Return scenario-scoped assets, optionally filtered by semantic type."""
        rows = self.nodes.loc[self.nodes["scenario_id"].fillna("").astype(str) == str(scenario_id)]
        if semantic_type is not None:
            rows = rows.loc[rows["semantic_type"] == semantic_type]
        return tuple(self._node_record(row) for _, row in rows.sort_values("node_id").iterrows())

    def providers_for_constraint(
        self,
        constraint_id: str,
        *,
        scenario_id: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Return flexibility providers located in a constraint zone."""
        zone_ids = self._constraint_zone_ids(constraint_id, scenario_id=scenario_id)
        provider_ids: set[str] = set()
        for zone_id in zone_ids:
            provider_ids.update(
                self.neighbors(
                    zone_id,
                    "LOCATED_IN_CONSTRAINT_ZONE",
                    direction="in",
                    scenario_id=scenario_id,
                )
            )
        return tuple(
            self._provider_record(provider_id)
            for provider_id in sorted(provider_ids)
            if self.get_node(provider_id) is not None
        )

    def trace_building_to_constraint(
        self,
        building_id: str,
        *,
        scenario_id: str | None = None,
    ) -> dict[str, Any]:
        """Trace a building to load, bus, providers, and constraint IDs."""
        if self.get_node(building_id) is None:
            raise KeyError(f"Semantic building node not found: {building_id}")
        load_ids = self.neighbors(building_id, "HAS_LOAD")
        bus_ids: set[str] = set()
        for load_id in load_ids:
            bus_ids.update(self.neighbors(load_id, "CONNECTED_TO"))

        providers = self._providers_for_building(building_id, scenario_id=scenario_id)
        constraint_ids = tuple(
            sorted(
                {
                    provider.get("constraint_zone_id")
                    for provider in providers
                    if provider.get("constraint_zone_id")
                }
            )
        )
        return {
            "building_id": building_id,
            "load_ids": tuple(sorted(load_ids)),
            "bus_ids": tuple(sorted(bus_ids)),
            "provider_ids": tuple(provider["provider_id"] for provider in providers),
            "constraint_ids": constraint_ids,
        }

    def timeseries_for_asset(
        self,
        asset_id: str,
        *,
        scenario_id: str | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Return time-series datasets relevant to an asset or its scenario."""
        scenario_ids: set[str] = set()
        node = self.get_node(asset_id)
        if node is not None and node.get("scenario_id"):
            scenario_ids.add(str(node["scenario_id"]))
        if scenario_id is not None:
            scenario_ids.add(str(scenario_id))
        if not scenario_ids:
            scenario_ids.update(
                self.nodes.loc[
                    self.nodes["semantic_type"] == "dt:TimeSeriesDataset",
                    "scenario_id",
                ].dropna().astype(str)
            )
        rows = self.nodes.loc[
            (self.nodes["semantic_type"] == "dt:TimeSeriesDataset")
            & (self.nodes["scenario_id"].fillna("").astype(str).isin(scenario_ids))
        ]
        if node is not None and node.get("semantic_type") == "ieee2030_5:EVSE":
            rows = rows.loc[rows["source_table"] == "ev_load_summary"]
        return tuple(self._node_record(row) for _, row in rows.sort_values("node_id").iterrows())

    def _matching_edges(
        self,
        node_id: str,
        relationship_type: str | None = None,
        *,
        direction: str,
        scenario_id: str | None = None,
    ) -> pd.DataFrame:
        if direction not in {"out", "in"}:
            raise ValueError("direction must be 'out' or 'in'")
        column = "source_id" if direction == "out" else "target_id"
        matches = self.edges.loc[self.edges[column] == node_id]
        if relationship_type is not None:
            matches = matches.loc[matches["relationship_type"] == relationship_type]
        if scenario_id is not None:
            matches = matches.loc[matches["scenario_id"].fillna("").astype(str) == str(scenario_id)]
        return matches

    def _constraint_zone_ids(
        self,
        constraint_id: str,
        *,
        scenario_id: str | None,
    ) -> tuple[str, ...]:
        zone_ids = set(
            self.neighbors(
                str(constraint_id),
                "CONSTRAINT_ZONE_FOR",
                direction="in",
                scenario_id=scenario_id,
            )
        )
        zones = self.nodes.loc[self.nodes["semantic_type"] == "cls:ConstraintZone"]
        if scenario_id is not None:
            zones = zones.loc[zones["scenario_id"].fillna("").astype(str) == str(scenario_id)]
        for _, row in zones.iterrows():
            props = _loads_json(row["properties"])
            if str(props.get("constraint_id")) == str(constraint_id):
                zone_ids.add(str(row["node_id"]))
        return tuple(sorted(zone_ids))

    def _providers_for_building(
        self,
        building_id: str,
        *,
        scenario_id: str | None,
    ) -> tuple[dict[str, Any], ...]:
        rows = self.nodes.loc[self.nodes["semantic_type"] == "cls:FlexibilityProvider"]
        if scenario_id is not None:
            rows = rows.loc[rows["scenario_id"].fillna("").astype(str) == str(scenario_id)]
        providers = []
        for _, row in rows.iterrows():
            record = self._provider_record(str(row["node_id"]))
            if record.get("building_id") == building_id:
                providers.append(record)
        return tuple(sorted(providers, key=lambda item: item["provider_id"]))

    def _provider_record(self, provider_id: str) -> dict[str, Any]:
        node = self.get_node(provider_id)
        if node is None:
            raise KeyError(f"Semantic provider node not found: {provider_id}")
        record = dict(node["properties"])
        record.update(
            {
                "provider_id": provider_id,
                "semantic_type": node["semantic_type"],
                "scenario_id": node.get("scenario_id"),
            }
        )
        return record

    @staticmethod
    def _group_neighbors(edges: pd.DataFrame, neighbor_column: str) -> dict[str, tuple[str, ...]]:
        grouped: dict[str, tuple[str, ...]] = {}
        for relationship_type, group in edges.groupby("relationship_type", sort=True):
            grouped[str(relationship_type)] = tuple(
                group[neighbor_column].dropna().astype(str).drop_duplicates().tolist()
            )
        return grouped

    @staticmethod
    def _node_record(row: pd.Series) -> dict[str, Any]:
        record = row.to_dict()
        record["properties"] = _loads_json(record.get("properties"))
        return record


__all__ = ["SemanticGraphRepository"]
