"""North America semantic mappings for the digital-twin parquet assets."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


NAMESPACES = {
    "cim": "https://cim.ucaiug.io/ns#",
    "brick": "https://brickschema.org/schema/Brick#",
    "s223": "http://data.ashrae.org/standard223#",
    "openadr": "https://openadr.org/ns#",
    "ieee2030_5": "https://standards.ieee.org/ieee/2030.5#",
    "efont": "http://www.semanticweb.org/hlee9/ontologies/2021/4/EF-core#",
    "gb": "https://www.greenbuttondata.org/ns#",
    "cls": "https://gridalyn.local/ontology/cls#",
    "dt": "https://gridalyn.local/ontology/digital-twin#",
}

RELATIONSHIP_TYPES = [
    "AGGREGATES",
    "ALLOWS",
    "CHARACTERIZES",
    "CONNECTS",
    "CONNECTED_TO",
    "CONSTRAINT_ZONE_FOR",
    "DESCRIBES_FLEXIBILITY",
    "ENABLES",
    "FEEDS",
    "HAS_EVSE",
    "HAS_FLEXIBILITY_RESOURCE",
    "HAS_LOAD",
    "IMPLEMENTS_CONTRACT",
    "INCLUDES_ASSET",
    "INCLUDES_PROVIDER",
    "LOCATED_IN_CONSTRAINT_ZONE",
    "MANAGES_PORTFOLIO",
    "OBSERVES",
    "OFFERS",
    "PARTICIPATES_IN",
    "PRODUCED",
    "QUANTIFIES",
    "TARGETS_CONSTRAINT",
]


def north_america_profile() -> dict[str, Any]:
    return {
        "semantic_profile": "north_america",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "namespaces": NAMESPACES,
        "primary_standards": {
            "grid_topology": ["IEC CIM", "IEC 61970", "IEC 61968", "CIM100"],
            "buildings": ["ASHRAE 223", "Brick Schema"],
            "building_flexibility": ["EFOnt"],
            "metering": ["Green Button", "NAESB ESPI"],
            "demand_response": ["OpenADR"],
            "ev_der_control": ["IEEE 2030.5"],
            "cls_market": ["gridalyn cls extension"],
        },
        "allowed_semantic_types": [
            "brick:Building",
            "cim:ACLineSegment",
            "cim:ConnectivityNode",
            "cim:EnergyConsumer",
            "cim:PowerTransformer",
            "cls:ConstraintZone",
            "cls:FlexibilityAggregator",
            "cls:FlexibilityOffer",
            "cls:FlexibilityPortfolio",
            "cls:FlexibilityProvider",
            "cls:HardCLSContract",
            "cls:SoftCLSContract",
            "dt:Scenario",
            "dt:ScenarioDevice",
            "dt:SimulationRun",
            "dt:TimeSeriesDataset",
            "efont:EnergyFlexibility",
            "efont:EnergyFlexibilityKPI",
            "efont:FlexibleLoadCharacteristic",
            "efont:FlexibleOperation",
            "efont:ThermallyActivatedBuildingSystem",
            "ieee2030_5:EVSE",
        ],
        "relationship_types": RELATIONSHIP_TYPES,
        "unit_conventions": {
            "active_power": "kW or MW, explicit in property name",
            "reactive_power": "kvar or Mvar, explicit in property name",
            "voltage": "kV or pu, explicit in property name",
            "current": "kA, explicit in property name",
        },
        "crosswalk_only_namespaces": ["saref"],
    }


def write_profile(path: Path) -> dict[str, Any]:
    profile = north_america_profile()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(profile, f, indent=2, sort_keys=True)
    return profile


def semantic_uri(qname: str) -> str:
    prefix, local_name = qname.split(":", 1)
    return f"{NAMESPACES[prefix]}{local_name}"


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


def _append_unique_edge(edges: list[dict[str, Any]], edge: dict[str, Any], seen: set[str]) -> None:
    if edge["edge_id"] in seen:
        return
    seen.add(edge["edge_id"])
    edges.append(edge)


def _append_unique_node(nodes: list[dict[str, Any]], node: dict[str, Any], seen: set[str]) -> None:
    if node["node_id"] in seen:
        return
    seen.add(node["node_id"])
    nodes.append(node)


def _append_efont_soft_cls_crosswalk(
    *,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    seen_edges: set[str],
    scenario_id: str,
    building_id: str,
    contract_id: str,
    row: dict[str, Any],
) -> None:
    resource_id = f"efont:resource:{scenario_id}:{building_id}:thermal"
    operation_id = f"efont:operation:{scenario_id}:{building_id}:soft_cls"
    flexibility_id = f"efont:flexibility:{scenario_id}:{building_id}:soft_cls"
    kpi_id = f"efont:kpi:{scenario_id}:{building_id}:maximum_reduced_demand"
    max_soft_kw = row.get("max_soft_kw")

    nodes.extend(
        [
            _node(
                resource_id,
                ["FlexibilityResource", "BuildingFlexibilityResource"],
                "efont:ThermallyActivatedBuildingSystem",
                "EFOnt",
                "asset_registry",
                resource_id,
                name=resource_id,
                scenario_id=scenario_id,
                properties={
                    "building_id": building_id,
                    "contract_id": contract_id,
                    "mapped_from": "cls:SoftCLSContract",
                    "application_scope": "BuildingLevelApplication",
                    "flexibility_resource": "thermally_activated_building_system",
                },
            ),
            _node(
                operation_id,
                ["FlexibleOperation", "SoftCLSOperation"],
                "efont:FlexibleOperation",
                "EFOnt",
                "asset_registry",
                operation_id,
                name=operation_id,
                scenario_id=scenario_id,
                properties={
                    "building_id": building_id,
                    "contract_id": contract_id,
                    "activation_method": "dynamic_operating_envelope",
                    "performance_goal": "reducePeakDemand",
                    "operation_mode": "temperature_setpoint_adjustment",
                },
            ),
            _node(
                flexibility_id,
                ["EnergyFlexibility", "SoftCLSFlexibility"],
                "efont:EnergyFlexibility",
                "EFOnt",
                "asset_registry",
                flexibility_id,
                name=flexibility_id,
                scenario_id=scenario_id,
                properties={
                    "building_id": building_id,
                    "contract_id": contract_id,
                    "max_reduced_demand_kw": max_soft_kw,
                    "cls_contract_type": row.get("contract_type"),
                    "performance_goal": "reducePeakDemand",
                },
            ),
            _node(
                kpi_id,
                ["EnergyFlexibilityKPI", "MaximumReducedDemand"],
                "efont:EnergyFlexibilityKPI",
                "EFOnt",
                "asset_registry",
                kpi_id,
                name="MaximumReducedDemand",
                scenario_id=scenario_id,
                properties={
                    "building_id": building_id,
                    "contract_id": contract_id,
                    "kpi": "MaximumReducedDemand",
                    "value_kw": max_soft_kw,
                    "unit": "kW",
                },
            ),
        ]
    )

    for edge in (
        _edge(
            building_id,
            "HAS_FLEXIBILITY_RESOURCE",
            resource_id,
            "dt:hasFlexibilityResource",
            "Gridalyn_DT",
            "asset_registry",
            resource_id,
            scenario_id=scenario_id,
        ),
        _edge(
            resource_id,
            "ALLOWS",
            operation_id,
            "efont:allows",
            "EFOnt",
            "asset_registry",
            operation_id,
            scenario_id=scenario_id,
        ),
        _edge(
            operation_id,
            "ENABLES",
            flexibility_id,
            "efont:enables",
            "EFOnt",
            "asset_registry",
            flexibility_id,
            scenario_id=scenario_id,
        ),
        _edge(
            kpi_id,
            "QUANTIFIES",
            flexibility_id,
            "efont:Quantifies",
            "EFOnt",
            "asset_registry",
            kpi_id,
            scenario_id=scenario_id,
        ),
        _edge(
            contract_id,
            "DESCRIBES_FLEXIBILITY",
            flexibility_id,
            "cls:describesFlexibility",
            "Gridalyn_CLS",
            "asset_registry",
            contract_id,
            scenario_id=scenario_id,
        ),
    ):
        _append_unique_edge(edges, edge, seen_edges)


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
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen_edges: set[str] = set()
    asset_registry = asset_registry if asset_registry is not None else pd.DataFrame()
    provider_registry = provider_registry if provider_registry is not None else pd.DataFrame()
    timeseries_manifests = timeseries_manifests or {}

    for row in buses.to_dict("records"):
        nodes.append(
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

    for row in lines.to_dict("records"):
        nodes.append(
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
            _append_unique_edge(
                edges,
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
                seen_edges,
            )

    for row in transformers.to_dict("records"):
        nodes.append(
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
            _append_unique_edge(
                edges,
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
                seen_edges,
            )

    connectivity_by_load = connectivity.set_index("load_id").to_dict("index") if not connectivity.empty else {}
    for row in buildings.to_dict("records"):
        building_id = row["building_id"]
        load_id = row["load_id"]
        load_bus_id = row.get("lv_bus_id")
        if load_id in connectivity_by_load:
            load_bus_id = connectivity_by_load[load_id].get("load_bus_id", load_bus_id)
        nodes.append(
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
        nodes.append(
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
        _append_unique_edge(
            edges,
            _edge(
                building_id,
                "HAS_LOAD",
                load_id,
                "dt:hasLoad",
                "Gridalyn_DT",
                "buildings",
                building_id,
            ),
            seen_edges,
        )
        if load_bus_id:
            _append_unique_edge(
                edges,
                _edge(
                    load_id,
                    "CONNECTED_TO",
                    load_bus_id,
                    "cim:ConnectivityNode",
                    "IEC_CIM",
                    "building_grid_connectivity",
                    load_id,
                ),
                seen_edges,
            )

    scenario_ids = set()
    if not asset_registry.empty:
        scenario_ids.update(asset_registry["scenario_id"].dropna().astype(str).unique())
    if not provider_registry.empty:
        scenario_ids.update(provider_registry["scenario_id"].dropna().astype(str).unique())
    for manifest in timeseries_manifests.values():
        for scenario in manifest.get("scenarios", []):
            if scenario.get("scenario_id"):
                scenario_ids.add(str(scenario["scenario_id"]))
    for scenario_id in sorted(scenario_ids):
        node_id = f"scenario:{scenario_id}"
        nodes.append(
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

    for row in asset_registry.to_dict("records"):
        scenario_id = str(row["scenario_id"])
        scenario_node = f"scenario:{scenario_id}"
        building_id = row["building_id"]
        _append_unique_edge(
            edges,
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
            seen_edges,
        )

        has_ev = bool(row.get("has_ev"))
        ev_id = _safe_str(row.get("ev_id"))
        soft = bool(row.get("soft_cls_participant"))
        hard = bool(row.get("hard_cls_enabled"))

        if has_ev and ev_id:
            nodes.append(
                _node(
                    ev_id,
                    ["EVSE", "DERAsset"],
                    "ieee2030_5:EVSE",
                    "IEEE_2030_5",
                    "asset_registry",
                    f"{scenario_id}:{ev_id}",
                    name=ev_id,
                    scenario_id=scenario_id,
                    properties={
                        "building_id": building_id,
                        "charger_kw": row.get("charger_kw"),
                        "max_hard_kw": row.get("max_hard_kw"),
                    },
                )
            )
            for edge in (
                _edge(
                    building_id,
                    "HAS_EVSE",
                    ev_id,
                    "dt:hasEVSE",
                    "Gridalyn_DT",
                    "asset_registry",
                    f"{scenario_id}:{building_id}:{ev_id}",
                    scenario_id=scenario_id,
                ),
                _edge(
                    scenario_node,
                    "INCLUDES_ASSET",
                    ev_id,
                    "dt:includesAsset",
                    "Gridalyn_DT",
                    "asset_registry",
                    f"{scenario_id}:{ev_id}",
                    scenario_id=scenario_id,
                ),
            ):
                _append_unique_edge(edges, edge, seen_edges)

        if soft:
            contract_id = f"contract:{scenario_id}:{building_id}:soft_cls"
            nodes.append(
                _node(
                    contract_id,
                    ["SoftCLSContract", "FlexibilityContract"],
                    "cls:SoftCLSContract",
                    "Gridalyn_CLS",
                    "asset_registry",
                    contract_id,
                    name=contract_id,
                    scenario_id=scenario_id,
                    properties={
                        "building_id": building_id,
                        "max_soft_kw": row.get("max_soft_kw"),
                        "contract_type": row.get("contract_type"),
                    },
                )
            )
            for edge in (
                _edge(
                    building_id,
                    "PARTICIPATES_IN",
                    contract_id,
                    "cls:participatesIn",
                    "Gridalyn_CLS",
                    "asset_registry",
                    contract_id,
                    scenario_id=scenario_id,
                ),
                _edge(
                    scenario_node,
                    "INCLUDES_ASSET",
                    contract_id,
                    "dt:includesAsset",
                    "Gridalyn_DT",
                    "asset_registry",
                    contract_id,
                    scenario_id=scenario_id,
                ),
            ):
                _append_unique_edge(edges, edge, seen_edges)
            _append_efont_soft_cls_crosswalk(
                nodes=nodes,
                edges=edges,
                seen_edges=seen_edges,
                scenario_id=scenario_id,
                building_id=building_id,
                contract_id=contract_id,
                row=row,
            )

        if has_ev and ev_id and hard:
            contract_id = f"contract:{scenario_id}:{ev_id}:hard_cls"
            hard_preferred = not soft
            nodes.append(
                _node(
                    contract_id,
                    ["HardCLSContract", "FlexibilityContract"],
                    "cls:HardCLSContract",
                    "Gridalyn_CLS",
                    "asset_registry",
                    contract_id,
                    name=contract_id,
                    scenario_id=scenario_id,
                    properties={
                        "ev_id": ev_id,
                        "building_id": building_id,
                        "max_hard_kw": row.get("max_hard_kw"),
                        "hard_preferred": hard_preferred,
                    },
                )
            )
            for edge in (
                _edge(
                    ev_id,
                    "ENABLES",
                    contract_id,
                    "cls:enables",
                    "Gridalyn_CLS",
                    "asset_registry",
                    contract_id,
                    scenario_id=scenario_id,
                ),
                _edge(
                    scenario_node,
                    "INCLUDES_ASSET",
                    contract_id,
                    "dt:includesAsset",
                    "Gridalyn_DT",
                    "asset_registry",
                    contract_id,
                    scenario_id=scenario_id,
                ),
            ):
                _append_unique_edge(edges, edge, seen_edges)

    if not provider_registry.empty:
        seen_nodes = {node["node_id"] for node in nodes}
        required_provider_cols = {
            "provider_id",
            "scenario_id",
            "provider_type",
            "building_id",
            "load_id",
            "ev_id",
            "pandapower_load",
            "load_bus_id",
            "feeder_bus_id",
            "constraint_zone_id",
            "constraint_zone_type",
            "available_capacity_kw",
            "base_cost_per_kw_h",
            "selection_priority",
        }
        missing_provider_cols = required_provider_cols - set(provider_registry.columns)
        if missing_provider_cols:
            raise ValueError(
                "provider_registry is missing required columns: "
                + ", ".join(sorted(missing_provider_cols))
            )

        for scenario_id in sorted(provider_registry["scenario_id"].dropna().astype(str).unique()):
            scenario_node = f"scenario:{scenario_id}"
            for provider_type, role_label in (
                ("soft_cls_building", "soft_cls"),
                ("hard_cls_ev", "hard_cls"),
            ):
                group = provider_registry.loc[
                    (provider_registry["scenario_id"].astype(str) == scenario_id)
                    & (provider_registry["provider_type"] == provider_type)
                ]
                if group.empty:
                    continue
                aggregator_id = f"aggregator:{scenario_id}:{role_label}"
                portfolio_id = f"portfolio:{scenario_id}:{role_label}"
                total_capacity_kw = float(group["available_capacity_kw"].sum())
                _append_unique_node(
                    nodes,
                    _node(
                        aggregator_id,
                        ["FlexibilityAggregator", "MarketParticipant"],
                        "cls:FlexibilityAggregator",
                        "Gridalyn_CLS",
                        "provider_registry",
                        aggregator_id,
                        name=aggregator_id,
                        scenario_id=scenario_id,
                        properties={
                            "scenario_id": scenario_id,
                            "provider_type": provider_type,
                            "aggregator_role": role_label,
                            "provider_count": int(len(group)),
                            "available_capacity_kw": total_capacity_kw,
                        },
                    ),
                    seen_nodes,
                )
                _append_unique_node(
                    nodes,
                    _node(
                        portfolio_id,
                        ["FlexibilityPortfolio"],
                        "cls:FlexibilityPortfolio",
                        "Gridalyn_CLS",
                        "provider_registry",
                        portfolio_id,
                        name=portfolio_id,
                        scenario_id=scenario_id,
                        properties={
                            "scenario_id": scenario_id,
                            "provider_type": provider_type,
                            "provider_count": int(len(group)),
                            "available_capacity_kw": total_capacity_kw,
                        },
                    ),
                    seen_nodes,
                )
                for edge in (
                    _edge(
                        scenario_node,
                        "INCLUDES_ASSET",
                        aggregator_id,
                        "dt:includesAsset",
                        "Gridalyn_DT",
                        "provider_registry",
                        aggregator_id,
                        scenario_id=scenario_id,
                    ),
                    _edge(
                        aggregator_id,
                        "MANAGES_PORTFOLIO",
                        portfolio_id,
                        "cls:managesPortfolio",
                        "Gridalyn_CLS",
                        "provider_registry",
                        portfolio_id,
                        scenario_id=scenario_id,
                    ),
                ):
                    _append_unique_edge(edges, edge, seen_edges)

        for row in provider_registry.to_dict("records"):
            scenario_id = str(row["scenario_id"])
            provider_type = str(row["provider_type"])
            if provider_type not in {"soft_cls_building", "hard_cls_ev"}:
                raise ValueError(f"Unsupported provider_type in provider_registry: {provider_type}")
            role_label = "soft_cls" if provider_type == "soft_cls_building" else "hard_cls"
            aggregator_id = f"aggregator:{scenario_id}:{role_label}"
            portfolio_id = f"portfolio:{scenario_id}:{role_label}"
            provider_id = str(row["provider_id"])
            offer_id = provider_id.replace("provider:", "offer:", 1)
            constraint_id = _safe_str(row.get("constraint_zone_id"))
            constraint_zone_id = f"constraint-zone:{scenario_id}:{constraint_id}" if constraint_id else None
            contract_id = (
                f"contract:{scenario_id}:{row['building_id']}:soft_cls"
                if provider_type == "soft_cls_building"
                else f"contract:{scenario_id}:{row['ev_id']}:hard_cls"
            )

            _append_unique_node(
                nodes,
                _node(
                    provider_id,
                    ["FlexibilityProvider", "MarketResource"],
                    "cls:FlexibilityProvider",
                    "Gridalyn_CLS_EFOnt_CIM",
                    "provider_registry",
                    provider_id,
                    name=provider_id,
                    scenario_id=scenario_id,
                    properties={
                        "provider_type": provider_type,
                        "building_id": row.get("building_id"),
                        "load_id": row.get("load_id"),
                        "ev_id": row.get("ev_id"),
                        "pandapower_load": row.get("pandapower_load"),
                        "load_bus_id": row.get("load_bus_id"),
                        "feeder_bus_id": row.get("feeder_bus_id"),
                        "constraint_zone_id": constraint_id,
                        "available_capacity_kw": row.get("available_capacity_kw"),
                        "base_cost_per_kw_h": row.get("base_cost_per_kw_h"),
                        "selection_priority": row.get("selection_priority"),
                        "scenario_device_ids": row.get("scenario_device_ids"),
                        "device_ids": row.get("device_ids"),
                        "building_model_id": row.get("building_model_id"),
                        "device_types": row.get("device_types"),
                        "scenario_device_count": row.get("scenario_device_count"),
                    },
                ),
                seen_nodes,
            )
            scenario_device_ids = _split_semicolon_values(row.get("scenario_device_ids"))
            device_ids = _split_semicolon_values(row.get("device_ids"))
            device_types = _split_semicolon_values(row.get("device_types"))
            for index, scenario_device_id in enumerate(scenario_device_ids):
                device_id = device_ids[index] if index < len(device_ids) else None
                device_type = device_types[index] if index < len(device_types) else None
                _append_unique_node(
                    nodes,
                    _node(
                        scenario_device_id,
                        ["ScenarioDevice", "FlexibilityResource"],
                        "dt:ScenarioDevice",
                        "Gridalyn_DT_CLS",
                        "provider_registry",
                        scenario_device_id,
                        name=scenario_device_id,
                        scenario_id=scenario_id,
                        properties={
                            "provider_id": provider_id,
                            "device_id": device_id,
                            "device_type": device_type,
                            "building_id": row.get("building_id"),
                            "building_model_id": row.get("building_model_id"),
                            "load_id": row.get("load_id"),
                            "load_bus_id": row.get("load_bus_id"),
                            "constraint_zone_id": constraint_id,
                        },
                    ),
                    seen_nodes,
                )
            _append_unique_node(
                nodes,
                _node(
                    offer_id,
                    ["FlexibilityOffer"],
                    "cls:FlexibilityOffer",
                    "Gridalyn_CLS",
                    "provider_registry",
                    offer_id,
                    name=offer_id,
                    scenario_id=scenario_id,
                    properties={
                        "provider_id": provider_id,
                        "provider_type": provider_type,
                        "available_capacity_kw": row.get("available_capacity_kw"),
                        "base_cost_per_kw_h": row.get("base_cost_per_kw_h"),
                        "selection_priority": row.get("selection_priority"),
                    },
                ),
                seen_nodes,
            )
            if constraint_zone_id and constraint_id:
                _append_unique_node(
                    nodes,
                    _node(
                        constraint_zone_id,
                        ["ConstraintZone", "LocationalMarketZone"],
                        "cls:ConstraintZone",
                        "Gridalyn_CLS_CIM",
                        "provider_registry",
                        constraint_zone_id,
                        name=constraint_zone_id,
                        scenario_id=scenario_id,
                        properties={
                            "constraint_id": constraint_id,
                            "constraint_type": row.get("constraint_zone_type"),
                            "scenario_id": scenario_id,
                        },
                    ),
                    seen_nodes,
                )

            for edge in (
                _edge(
                    f"scenario:{scenario_id}",
                    "INCLUDES_ASSET",
                    provider_id,
                    "dt:includesAsset",
                    "Gridalyn_DT",
                    "provider_registry",
                    provider_id,
                    scenario_id=scenario_id,
                ),
                _edge(
                    aggregator_id,
                    "AGGREGATES",
                    provider_id,
                    "cls:aggregates",
                    "Gridalyn_CLS",
                    "provider_registry",
                    provider_id,
                    scenario_id=scenario_id,
                ),
                _edge(
                    portfolio_id,
                    "INCLUDES_PROVIDER",
                    provider_id,
                    "cls:includesProvider",
                    "Gridalyn_CLS",
                    "provider_registry",
                    provider_id,
                    scenario_id=scenario_id,
                ),
                _edge(
                    provider_id,
                    "OFFERS",
                    offer_id,
                    "cls:offers",
                    "Gridalyn_CLS",
                    "provider_registry",
                    offer_id,
                    scenario_id=scenario_id,
                ),
                _edge(
                    provider_id,
                    "IMPLEMENTS_CONTRACT",
                    contract_id,
                    "cls:implementsContract",
                    "Gridalyn_CLS",
                    "provider_registry",
                    contract_id,
                    scenario_id=scenario_id,
                ),
            ):
                _append_unique_edge(edges, edge, seen_edges)

            for scenario_device_id in scenario_device_ids:
                _append_unique_edge(
                    edges,
                    _edge(
                        provider_id,
                        "HAS_FLEXIBILITY_RESOURCE",
                        scenario_device_id,
                        "cls:hasFlexibilityResource",
                        "Gridalyn_CLS",
                        "provider_registry",
                        scenario_device_id,
                        scenario_id=scenario_id,
                    ),
                    seen_edges,
                )

            if constraint_zone_id and constraint_id:
                for edge in (
                    _edge(
                        provider_id,
                        "LOCATED_IN_CONSTRAINT_ZONE",
                        constraint_zone_id,
                        "cls:locatedInConstraintZone",
                        "Gridalyn_CLS",
                        "provider_registry",
                        constraint_zone_id,
                        scenario_id=scenario_id,
                    ),
                    _edge(
                        offer_id,
                        "TARGETS_CONSTRAINT",
                        constraint_zone_id,
                        "cls:targetsConstraint",
                        "Gridalyn_CLS",
                        "provider_registry",
                        constraint_zone_id,
                        scenario_id=scenario_id,
                    ),
                    _edge(
                        constraint_zone_id,
                        "CONSTRAINT_ZONE_FOR",
                        constraint_id,
                        "cls:constraintZoneFor",
                        "Gridalyn_CLS_CIM",
                        "provider_registry",
                        constraint_id,
                        scenario_id=scenario_id,
                    ),
                ):
                    _append_unique_edge(edges, edge, seen_edges)

    for manifest_name, manifest in timeseries_manifests.items():
        for scenario in manifest.get("scenarios", []):
            scenario_id = scenario.get("scenario_id")
            if not scenario_id:
                continue
            scenario_id = str(scenario_id)
            run_id = f"simulation:{scenario_id}:{manifest_name}"
            nodes.append(
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
                nodes.append(
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
                    _append_unique_edge(edges, edge, seen_edges)

    nodes_df = pd.DataFrame(nodes).drop_duplicates("node_id").sort_values("node_id").reset_index(drop=True)
    edges_df = pd.DataFrame(edges).drop_duplicates("edge_id").sort_values("edge_id").reset_index(drop=True)
    profile = north_america_profile()
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "semantic_profile": profile["semantic_profile"],
        "namespaces": profile["namespaces"],
        "node_count": int(len(nodes_df)),
        "edge_count": int(len(edges_df)),
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
            "nodes": "digital_twin/semantic/nodes.parquet",
            "edges": "digital_twin/semantic/edges.parquet",
            "profile": "digital_twin/semantic/profile_north_america.json",
            "validation_report": "digital_twin/semantic/validation_report.json",
        },
    }
    expected_counts = {"buildings": 3235, "buses": 3562, "lines": 3398, "transformers": 163, "scenarios": 5}
    manifest["count_checks"] = {
        key: {"expected": expected, "actual": manifest["source_counts"].get(key), "ok": manifest["source_counts"].get(key) == expected}
        for key, expected in expected_counts.items()
    }
    return nodes_df, edges_df, manifest
