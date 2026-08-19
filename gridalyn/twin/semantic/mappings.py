"""North America semantic mappings for the digital-twin parquet assets.

This module is the orchestrator. It used to be the whole graph builder: an
822-line ``build_semantic_graph`` interleaving eight concerns and deduplicating
three different ways. The record constructors now live in
:mod:`gridalyn.twin.semantic.records`, identity in
:mod:`gridalyn.twin.semantic.builder`, and one emitter per source table in
:mod:`gridalyn.twin.semantic.emitters`.

The emitted graph is unchanged -- verified byte-for-byte against the shipped
twin (74 286 nodes, 147 065 edges) before and after the split.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from gridalyn.twin.semantic import emitters
from gridalyn.twin.semantic.builder import SemanticGraphBuilder
from gridalyn.twin.semantic.profile import (  # noqa: F401  (re-exported for workflow scripts)
    north_america_profile,
    profile_with_capabilities,
    semantic_uri,
    write_profile,
)
from gridalyn.twin.semantic.records import (  # noqa: F401  (re-exported: legacy import site)
    _clean_value,
    _edge,
    _json_properties,
    _node,
    _safe_str,
    _split_semicolon_values,
)


def build_semantic_graph(
    *,
    buses: pd.DataFrame,
    lines: pd.DataFrame,
    transformers: pd.DataFrame,
    buildings: pd.DataFrame,
    connectivity: pd.DataFrame,
    asset_registry: pd.DataFrame | None = None,
    provider_registry: pd.DataFrame | None = None,
    timeseries_manifests: dict[str, Any] | None = None,
    capabilities: set[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Build the semantic node/edge graph from the canonical twin tables.

    Args:
        buses: ``grid_buses`` table.
        lines: ``grid_lines`` table.
        transformers: ``grid_transformers`` table.
        buildings: ``buildings`` table.
        connectivity: ``building_grid_connectivity`` table.
        asset_registry: Scenario asset registry; empty when absent.
        provider_registry: Flexibility provider registry; empty when absent.
        timeseries_manifests: Run manifests keyed by name.
        capabilities: Declared semantic capabilities (Phase 21 re-layering).
            ``None`` preserves the pre-re-layering graph (the ``flexibility``
            capability is assumed, so existing callers stay value-identical);
            an explicit set builds the model-first core plus the declared
            capabilities (e.g. ``set()`` for a pure model-first graph, or
            ``{"flexibility"}`` for the full graph).

    Returns:
        ``(nodes, edges, manifest)``. The frames are sorted by ID, so the order
        the emitters run in does not reach the artifact.
    """
    asset_registry = asset_registry if asset_registry is not None else pd.DataFrame()
    provider_registry = (
        provider_registry if provider_registry is not None else pd.DataFrame()
    )
    timeseries_manifests = timeseries_manifests or {}
    # ``None`` preserves the pre-Phase-21 graph for existing callers; an
    # explicit set is the declared-capability (model-first) contract.
    capabilities = {"flexibility"} if capabilities is None else set(capabilities)

    builder = SemanticGraphBuilder()
    emitters.emit_buses(builder, buses)
    emitters.emit_lines(builder, lines)
    emitters.emit_transformers(builder, transformers)
    emitters.emit_premises(builder, buildings, connectivity)
    scenario_ids = emitters.collect_scenario_ids(
        asset_registry, provider_registry, timeseries_manifests
    )
    emitters.emit_scenarios(builder, scenario_ids)
    emitters.emit_asset_registry(builder, asset_registry)
    if "flexibility" in capabilities:
        from gridalyn.twin.semantic.capabilities.flexibility import (
            extend_graph_with_flexibility,
        )

        extend_graph_with_flexibility(builder, asset_registry, provider_registry)
    emitters.emit_timeseries_runs(builder, timeseries_manifests)

    node_count = builder.node_count
    edge_count = builder.edge_count
    nodes_df, edges_df = builder.to_frames()
    profile = profile_with_capabilities(capabilities)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "semantic_profile": profile["semantic_profile"],
        "namespaces": profile["namespaces"],
        "node_count": node_count,
        "edge_count": edge_count,
        "source_counts": {
            "buses": int(len(buses)),
            "lines": int(len(lines)),
            "transformers": int(len(transformers)),
            "buildings": int(len(buildings)),
            "asset_registry_rows": int(len(asset_registry)),
            "provider_registry_rows": int(len(provider_registry)),
            "scenarios": int(len(scenario_ids)),
        },
        "artifacts": {
            "nodes": "instances/default/digital_twin/semantic/nodes.parquet",
            "edges": "instances/default/digital_twin/semantic/edges.parquet",
            "profile": (
                "instances/default/digital_twin/semantic/profile_north_america.json"
            ),
            "validation_report": (
                "instances/default/digital_twin/semantic/validation_report.json"
            ),
        },
    }
    # NOTE: ``count_checks`` is intentionally NOT computed here. The expected
    # counts are twin-specific regression pins; they belong at the workflow
    # script layer (generate_digital_twin_semantic_graph.py), not embedded in
    # a library function (Phase 9, finding G8).
    return nodes_df, edges_df, manifest
