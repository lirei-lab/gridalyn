"""One emitter per source table, each writing into a shared builder — the
model-first semantic core.

``build_semantic_graph`` was 822 lines interleaving eight concerns -- topology,
premises, scenario discovery, the EV/CLS asset registry, the flexibility
provider registry with its own 14-column schema check, run manifests, and the
frame assembly. Splitting them by SOURCE TABLE is the seam that holds: each
emitter changes when its own table's schema changes and for no other reason.

**Phase 21 re-layering (2026-08-17):** this module is now the model-first
semantic core. It emits only generic CIM/Brick topology, premises, scenarios
and run provenance. The flexibility layer (CLS/EFOnt/market ontology, EVSE/DER
nodes, provider registry, the 14-column provider-schema re-declaration) moved
to :mod:`gridalyn.twin.semantic.capabilities.flexibility`, an on-demand
capability a project declares through its semantic profile. With the
capability ON the emitted graph is value-identical to the pre-re-layering
graph (R7); with it OFF the graph carries only the model-first core.

Every emitter takes the accumulator rather than raw lists, so node and edge
identity is resolved in exactly one place --
:class:`~gridalyn.twin.semantic.builder.SemanticGraphBuilder`. The function
this replaced used three different deduplication mechanisms, and which one a
given section reached for was historical accident.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from gridalyn.twin.network.schema import (
    BUILDING_GRID_CONNECTIVITY,
    BUILDINGS,
    ROLE_BUS,
    table_schema,
)
from gridalyn.twin.semantic.builder import SemanticGraphBuilder
from gridalyn.twin.semantic.records import _edge, _node, _safe_str


def collect_scenario_ids(
    asset_registry: pd.DataFrame,
    provider_registry: pd.DataFrame,
    timeseries_manifests: dict[str, Any],
) -> set[str]:
    """Discover every scenario ID the three heterogeneous sources mention.

    Args:
        asset_registry: Scenario asset registry, possibly empty.
        provider_registry: Flexibility provider registry, possibly empty.
        timeseries_manifests: Run manifests keyed by name.

    Returns:
        The union of scenario IDs, as strings.
    """
    scenario_ids = set()
    if not asset_registry.empty:
        scenario_ids.update(asset_registry["scenario_id"].dropna().astype(str).unique())
    if not provider_registry.empty:
        scenario_ids.update(
            provider_registry["scenario_id"].dropna().astype(str).unique()
        )
    for manifest in timeseries_manifests.values():
        for scenario in manifest.get("scenarios", []):
            if scenario.get("scenario_id"):
                scenario_ids.add(str(scenario["scenario_id"]))
    return scenario_ids


def emit_scenarios(builder: SemanticGraphBuilder, scenario_ids: set[str]) -> None:
    """Emit one Scenario node per discovered scenario ID.

    Args:
        builder: Accumulator that owns node and edge identity.
        scenario_ids: IDs from :func:`collect_scenario_ids`.
    """
    for scenario_id in sorted(scenario_ids):
        node_id = f"scenario:{scenario_id}"
        builder.add_node(
            _node(
                node_id,
                ["Scenario"],
                "dt:Scenario",
                "Gridalyn_DT",
                "scenario_manifest",
                scenario_id,
                name=scenario_id,
                scenario_id=scenario_id,
                properties={"scenario_id": scenario_id},
            )
        )


def emit_buses(
    builder: SemanticGraphBuilder,
    buses: pd.DataFrame,
) -> None:
    """Emit one ConnectivityNode per grid bus.

    Args:
        builder: Accumulator that owns node and edge identity.
    """
    for row in buses.to_dict("records"):
        builder.add_node(
            _node(
                row["bus_id"],
                ["ConnectivityNode", "GridNode"],
                "cim:ConnectivityNode",
                "IEC_CIM",
                "grid_buses",
                row["bus_id"],
                name=_safe_str(row.get("name")),
                properties={
                    "pandapower_bus": row.get("pandapower_bus"),
                    "voltage_kv": row.get("voltage_kv"),
                    "category": row.get("category"),
                    "lat": row.get("lat"),
                    "lon": row.get("lon"),
                    "in_service": row.get("in_service"),
                },
            )
        )


def emit_lines(
    builder: SemanticGraphBuilder,
    lines: pd.DataFrame,
) -> None:
    """Emit ACLineSegment nodes and their terminal CONNECTS edges.

    Args:
        builder: Accumulator that owns node and edge identity.
    """
    for row in lines.to_dict("records"):
        builder.add_node(
            _node(
                row["line_id"],
                ["ACLineSegment", "GridAsset"],
                "cim:ACLineSegment",
                "IEC_CIM",
                "grid_lines",
                row["line_id"],
                name=_safe_str(row.get("name")),
                properties={
                    "pandapower_line": row.get("pandapower_line"),
                    "length_km": row.get("length_km"),
                    "max_i_ka": row.get("max_i_ka"),
                    "category": row.get("category"),
                    "in_service": row.get("in_service"),
                },
            )
        )
        for bus_key in ("from_bus_id", "to_bus_id"):
            builder.add_edge(
                _edge(
                    row["line_id"],
                    "CONNECTS",
                    row[bus_key],
                    "cim:ConnectivityNode",
                    "IEC_CIM",
                    "grid_lines",
                    row["line_id"],
                    properties={"terminal": bus_key},
                ),
            )


def emit_transformers(
    builder: SemanticGraphBuilder,
    transformers: pd.DataFrame,
) -> None:
    """Emit PowerTransformer nodes and their FEEDS edges.

    Args:
        builder: Accumulator that owns node and edge identity.
    """
    for row in transformers.to_dict("records"):
        builder.add_node(
            _node(
                row["transformer_id"],
                ["PowerTransformer", "GridAsset"],
                "cim:PowerTransformer",
                "IEC_CIM",
                "grid_transformers",
                row["transformer_id"],
                name=_safe_str(row.get("name")),
                properties={
                    "pandapower_trafo": row.get("pandapower_trafo"),
                    "sn_mva": row.get("sn_mva"),
                    "vn_hv_kv": row.get("vn_hv_kv"),
                    "vn_lv_kv": row.get("vn_lv_kv"),
                    "in_service": row.get("in_service"),
                },
            )
        )
        for bus_key in ("hv_bus_id", "lv_bus_id"):
            builder.add_edge(
                _edge(
                    row["transformer_id"],
                    "FEEDS",
                    row[bus_key],
                    "cim:ConnectivityNode",
                    "IEC_CIM",
                    "grid_transformers",
                    row["transformer_id"],
                    properties={"terminal": bus_key},
                ),
            )


def emit_premises(
    builder: SemanticGraphBuilder,
    buildings: pd.DataFrame,
    connectivity: pd.DataFrame,
) -> None:
    """Emit Building and EnergyConsumer nodes and their connectivity edges.

    Args:
        builder: Accumulator that owns node and edge identity.
        buildings: The canonical ``buildings`` table.
        connectivity: The canonical ``building_grid_connectivity`` table.
    """
    buildings_bus_column = table_schema(BUILDINGS).resolve(buildings, ROLE_BUS)
    connectivity_bus_column = table_schema(BUILDING_GRID_CONNECTIVITY).resolve(
        connectivity, ROLE_BUS
    )
    connectivity_by_load = (
        connectivity.set_index("load_id").to_dict("index")
        if not connectivity.empty
        else {}
    )
    for row in buildings.to_dict("records"):
        building_id = row["building_id"]
        load_id = row["load_id"]
        load_bus_id = row.get(buildings_bus_column)
        if load_id in connectivity_by_load:
            load_bus_id = connectivity_by_load[load_id].get(
                connectivity_bus_column, load_bus_id
            )
        builder.add_node(
            _node(
                building_id,
                ["Building", "Asset"],
                "brick:Building",
                "ASHRAE_223_BRICK",
                "buildings",
                building_id,
                name=building_id,
                properties={
                    "area_m2": row.get("area_m2"),
                    "lat": row.get("lat"),
                    "lon": row.get("lon"),
                    "source_building_id": row.get("source_building_id"),
                },
            )
        )
        builder.add_node(
            _node(
                load_id,
                ["EnergyConsumer", "GridNode"],
                "cim:EnergyConsumer",
                "IEC_CIM",
                "buildings",
                load_id,
                name=load_id,
                properties={
                    "pandapower_load": row.get("pandapower_load"),
                    "static_p_mw": row.get("static_p_mw"),
                    "static_q_mvar": row.get("static_q_mvar"),
                },
            )
        )
        builder.add_edge(
            _edge(
                building_id,
                "HAS_LOAD",
                load_id,
                "dt:hasLoad",
                "Gridalyn_DT",
                "buildings",
                building_id,
            ),
        )
        if load_bus_id:
            builder.add_edge(
                _edge(
                    load_id,
                    "CONNECTED_TO",
                    load_bus_id,
                    "cim:ConnectivityNode",
                    "IEC_CIM",
                    "building_grid_connectivity",
                    load_id,
                ),
            )


def emit_asset_registry(
    builder: SemanticGraphBuilder,
    asset_registry: pd.DataFrame,
) -> None:
    """Emit the generic scenario-includes-asset edges from the asset registry.

    The EVSE/CLS/EFOnt part of the asset registry is the flexibility layer and
    lives in :mod:`gridalyn.twin.semantic.capabilities.flexibility`; this
    emitter keeps only the model-first scenario → building membership edges.

    Args:
        builder: Accumulator that owns node and edge identity.
        asset_registry: Scenario asset registry; empty is a no-op.
    """
    if asset_registry.empty:
        return
    for row in asset_registry.to_dict("records"):
        scenario_id = str(row["scenario_id"])
        scenario_node = f"scenario:{scenario_id}"
        building_id = row["building_id"]
        builder.add_edge(
            _edge(
                scenario_node,
                "INCLUDES_ASSET",
                building_id,
                "dt:includesAsset",
                "Gridalyn_DT",
                "asset_registry",
                f"{scenario_id}:{building_id}",
                scenario_id=scenario_id,
            ),
        )


def emit_timeseries_runs(
    builder: SemanticGraphBuilder,
    timeseries_manifests: dict[str, Any],
) -> None:
    """Emit SimulationRun and TimeSeriesDataset provenance from run manifests.

    Args:
        builder: Accumulator that owns node and edge identity.
    """
    for manifest_name, manifest in timeseries_manifests.items():
        for scenario in manifest.get("scenarios", []):
            scenario_id = scenario.get("scenario_id")
            if not scenario_id:
                continue
            scenario_id = str(scenario_id)
            run_id = f"simulation:{scenario_id}:{manifest_name}"
            builder.add_node(
                _node(
                    run_id,
                    ["SimulationRun"],
                    "dt:SimulationRun",
                    "Gridalyn_DT",
                    manifest_name,
                    run_id,
                    name=run_id,
                    scenario_id=scenario_id,
                    properties={"manifest": manifest_name},
                )
            )
            paths = scenario.get("paths") or {"dataset": scenario.get("path")}
            for kind, path in paths.items():
                if not path:
                    continue
                dataset_id = f"timeseries:{scenario_id}:{manifest_name}:{kind}"
                builder.add_node(
                    _node(
                        dataset_id,
                        ["TimeSeriesDataset"],
                        "dt:TimeSeriesDataset",
                        "Green_Button_ESPI",
                        manifest_name,
                        str(path),
                        name=dataset_id,
                        scenario_id=scenario_id,
                        properties={"path": path, "kind": kind},
                    )
                )
                for edge in (
                    _edge(
                        run_id,
                        "PRODUCED",
                        dataset_id,
                        "dt:produced",
                        "Gridalyn_DT",
                        manifest_name,
                        dataset_id,
                        scenario_id=scenario_id,
                    ),
                    _edge(
                        dataset_id,
                        "OBSERVES",
                        f"scenario:{scenario_id}",
                        "dt:observes",
                        "Gridalyn_DT",
                        manifest_name,
                        dataset_id,
                        scenario_id=scenario_id,
                    ),
                ):
                    builder.add_edge(edge)


__all__ = [
    "collect_scenario_ids",
    "emit_asset_registry",
    "emit_buses",
    "emit_lines",
    "emit_premises",
    "emit_scenarios",
    "emit_timeseries_runs",
    "emit_transformers",
]
