"""One emitter per source table, each writing into a shared builder.

``build_semantic_graph`` was 822 lines interleaving eight concerns -- topology,
premises, scenario discovery, the EV/CLS asset registry, the flexibility
provider registry with its own 14-column schema check, run manifests, and the
frame assembly. Splitting them by SOURCE TABLE is the seam that holds: each
emitter changes when its own table's schema changes and for no other reason.

Every emitter takes the accumulator rather than raw lists, so node and edge
identity is resolved in exactly one place --
:class:`~gridalyn.twin.semantic.builder.SemanticGraphBuilder`. The function
this replaced used three different deduplication mechanisms, and which one a
given section reached for was historical accident.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from gridalyn.twin.semantic.builder import SemanticGraphBuilder
from gridalyn.twin.semantic.records import (
    _edge,
    _node,
    _safe_str,
    _split_semicolon_values,
)


def _append_efont_soft_cls_crosswalk(
    *,
    builder: SemanticGraphBuilder,
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

    for _efont_node in [
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
    ]:
        builder.add_node(_efont_node)

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
        builder.add_edge(edge)


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
    """
    connectivity_by_load = (
        connectivity.set_index("load_id").to_dict("index")
        if not connectivity.empty
        else {}
    )
    for row in buildings.to_dict("records"):
        building_id = row["building_id"]
        load_id = row["load_id"]
        load_bus_id = row.get("lv_bus_id")
        if load_id in connectivity_by_load:
            load_bus_id = connectivity_by_load[load_id].get("load_bus_id", load_bus_id)
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
    """Emit EV/CLS market nodes and edges from the scenario asset registry.

    Args:
        builder: Accumulator that owns node and edge identity.
    """
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

        has_ev = bool(row.get("has_ev"))
        ev_id = _safe_str(row.get("ev_id"))
        soft = bool(row.get("soft_cls_participant"))
        hard = bool(row.get("hard_cls_enabled"))

        if has_ev and ev_id:
            builder.add_node(
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
                builder.add_edge(edge)

        if soft:
            contract_id = f"contract:{scenario_id}:{building_id}:soft_cls"
            builder.add_node(
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
                builder.add_edge(edge)
            _append_efont_soft_cls_crosswalk(
                builder=builder,
                scenario_id=scenario_id,
                building_id=building_id,
                contract_id=contract_id,
                row=row,
            )

        if has_ev and ev_id and hard:
            contract_id = f"contract:{scenario_id}:{ev_id}:hard_cls"
            hard_preferred = not soft
            builder.add_node(
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
                builder.add_edge(edge)


def _require_provider_columns(provider_registry: pd.DataFrame) -> None:
    """Fail loudly when the provider registry is missing a declared column.

    Args:
        provider_registry: The frame produced by ``operations.build_provider_registry``.

    Raises:
        ValueError: Naming every missing column. This contract belongs to the
            operations layer, which is ABOVE twin; the columns are restated
            here because knowledge cannot flow downward as an import.
    """
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


def _emit_provider_aggregates(
    builder: SemanticGraphBuilder, provider_registry: pd.DataFrame
) -> None:
    """Emit one aggregator and portfolio per (scenario, provider role).

    Args:
        builder: Accumulator that owns node and edge identity.
        provider_registry: Validated provider registry.
    """
    for scenario_id in sorted(
        provider_registry["scenario_id"].dropna().astype(str).unique()
    ):
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
            builder.add_node(
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
            )
            builder.add_node(
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
                builder.add_edge(edge)


def _emit_provider_offers(
    builder: SemanticGraphBuilder, provider_registry: pd.DataFrame
) -> None:
    """Emit per-provider offer nodes and their constraint-zone membership.

    Args:
        builder: Accumulator that owns node and edge identity.
        provider_registry: Validated provider registry.
    """
    for row in provider_registry.to_dict("records"):
        scenario_id = str(row["scenario_id"])
        provider_type = str(row["provider_type"])
        if provider_type not in {"soft_cls_building", "hard_cls_ev"}:
            raise ValueError(
                f"Unsupported provider_type in provider_registry: {provider_type}"
            )
        role_label = "soft_cls" if provider_type == "soft_cls_building" else "hard_cls"
        aggregator_id = f"aggregator:{scenario_id}:{role_label}"
        portfolio_id = f"portfolio:{scenario_id}:{role_label}"
        provider_id = str(row["provider_id"])
        offer_id = provider_id.replace("provider:", "offer:", 1)
        constraint_id = _safe_str(row.get("constraint_zone_id"))
        constraint_zone_id = (
            f"constraint-zone:{scenario_id}:{constraint_id}" if constraint_id else None
        )
        contract_id = (
            f"contract:{scenario_id}:{row['building_id']}:soft_cls"
            if provider_type == "soft_cls_building"
            else f"contract:{scenario_id}:{row['ev_id']}:hard_cls"
        )

        builder.add_node(
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
        )
        scenario_device_ids = _split_semicolon_values(row.get("scenario_device_ids"))
        device_ids = _split_semicolon_values(row.get("device_ids"))
        device_types = _split_semicolon_values(row.get("device_types"))
        for index, scenario_device_id in enumerate(scenario_device_ids):
            device_id = device_ids[index] if index < len(device_ids) else None
            device_type = device_types[index] if index < len(device_types) else None
            builder.add_node(
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
            )
        builder.add_node(
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
        )
        if constraint_zone_id and constraint_id:
            builder.add_node(
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
            builder.add_edge(edge)

        for scenario_device_id in scenario_device_ids:
            builder.add_edge(
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
                builder.add_edge(edge)


def emit_provider_registry(
    builder: SemanticGraphBuilder,
    provider_registry: pd.DataFrame,
) -> None:
    """Emit flexibility aggregator, portfolio, offer and constraint-zone nodes.

    Args:
        builder: Accumulator that owns node and edge identity.
        provider_registry: Flexibility provider registry; empty is a no-op.
    """
    if provider_registry.empty:
        return
    _require_provider_columns(provider_registry)
    _emit_provider_aggregates(builder, provider_registry)
    _emit_provider_offers(builder, provider_registry)


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
    "emit_provider_registry",
    "emit_scenarios",
    "emit_timeseries_runs",
    "emit_transformers",
]
