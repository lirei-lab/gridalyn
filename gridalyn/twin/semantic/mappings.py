"""North America semantic mappings for the digital-twin parquet assets.

This module is the orchestrator. It used to be the whole graph builder: an
822-line ``build_semantic_graph`` interleaving eight concerns and deduplicating
three different ways. The record constructors now live in
:mod:`gridalyn.twin.semantic.records`, identity in
:mod:`gridalyn.twin.semantic.builder`, and one emitter per source table in
:mod:`gridalyn.twin.semantic.emitters`.

**Capabilities resolve by ID (2026-09-10).** Declared capabilities are resolved
through the semantic capability registry -- an unregistered name raises instead
of being ignored -- composed into the profile, and the profile is handed to the
builder, which refuses a node type or a relationship predicate the profile does
not declare. Each active capability
then extends the graph through its own declared extender.
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
    resolve_declared_capabilities,
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
from gridalyn.twin.semantic.registry import (
    SemanticCapabilityRegistry,
    default_semantic_capability_registry,
)
from gridalyn.twin.semantic.vocabulary import CapabilityInputs


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
    registry: SemanticCapabilityRegistry | None = None,
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
        capabilities: Declared semantic capability IDs. ``None`` applies the
            legacy default (``flexibility``); an explicit set builds the
            model-first core plus exactly those capabilities (``set()`` for a
            pure model-first graph).
        registry: Capability registry to resolve against; defaults to the
            shared default registry.

    Returns:
        ``(nodes, edges, manifest)``. The frames are sorted by ID, so the order
        the emitters run in does not reach the artifact. The manifest records
        the capabilities the graph was built with, which is what
        ``gridalyn semantic validate`` validates it against.

    Raises:
        UnknownSemanticCapabilityError: A declared capability is not registered.
        ValueError: The composed profile is inconsistent, or an emitter produced
            a type or a predicate the profile does not declare.
    """
    asset_registry = asset_registry if asset_registry is not None else pd.DataFrame()
    provider_registry = (
        provider_registry if provider_registry is not None else pd.DataFrame()
    )
    timeseries_manifests = timeseries_manifests or {}
    declared = resolve_declared_capabilities(capabilities)
    registry = registry or default_semantic_capability_registry()
    profile = profile_with_capabilities(declared, registry=registry)
    active = registry.resolve(declared)

    builder = SemanticGraphBuilder(profile)
    emitters.emit_buses(builder, buses)
    emitters.emit_lines(builder, lines)
    emitters.emit_transformers(builder, transformers)
    emitters.emit_premises(builder, buildings, connectivity)
    scenario_ids = emitters.collect_scenario_ids(
        asset_registry, provider_registry, timeseries_manifests
    )
    emitters.emit_scenarios(builder, scenario_ids)
    emitters.emit_asset_registry(builder, asset_registry)
    inputs = CapabilityInputs(
        buses=buses,
        lines=lines,
        transformers=transformers,
        buildings=buildings,
        connectivity=connectivity,
        asset_registry=asset_registry,
        provider_registry=provider_registry,
        timeseries_manifests=timeseries_manifests,
    )
    for capability in active:
        if capability.extend is not None:
            capability.extend(builder, inputs)
    emitters.emit_timeseries_runs(builder, timeseries_manifests)

    node_count = builder.node_count
    edge_count = builder.edge_count
    nodes_df, edges_df = builder.to_frames()
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "semantic_profile": profile["semantic_profile"],
        "capabilities": profile["capabilities"],
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
