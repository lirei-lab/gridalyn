"""The on-demand **flexibility** semantic capability (Phase 21 re-layering).

The default semantic graph is model-first: it emits only generic CIM/Brick
topology, premises, scenarios and run provenance (see
:mod:`gridalyn.twin.semantic.emitters`). Everything in this module is the
**flexibility layer** — the flexint/EFOnt/market ontology, the EV charging-station
nodes, the 14-column provider-schema re-declaration, and the
flexibility-specific repository queries — and is applied only when a project
declares the ``flexibility`` semantic capability.

Why it lives here and not in ``emitters.py``: before Phase 21 the flexibility
ontology was emitted by default and ``emitters.py`` re-declared the operations
provider schema with the comment "knowledge cannot flow downward as an
import". The re-layering keeps that honesty but scopes it: the operations
provider contract is still restated here (it cannot be imported downward), yet
it is now on an **on-demand layer** rather than in the model-first default.

The capability is declared configuration (a profile), never an upward import:
``operations`` still never imports this module.

**Declared as data (2026-09-10).** :data:`FLEXIBILITY_CAPABILITY`
states the namespaces, types, relationships (one predicate, a domain, a
range, optionally a cardinality) and scenario count rules this layer adds;
the default semantic capability registry resolves it by ID. Two relationships
changed in that re-base: the EVSE-to-Hard-CLS edge is ``ENABLES_CONTRACT``
(``flexint:enablesContract``), because it shared the label ``ENABLES`` with EFOnt's
operation-to-flexibility property while meaning something else; and
provider-to-device ``HAS_FLEXIBILITY_RESOURCE`` edges now carry
``dt:hasFlexibilityResource``, the predicate the building-to-resource edges of
the same relationship already carried.

**Persistent IRIs (2026-09-11).** ``cls:`` on the unresolvable
``gridalyn.local`` host became ``flexint:`` on w3id.org. The Soft and Hard
contract classes became one ``flexint:CurtailmentContract`` whose
``contract_mode`` property says which, because the acronym their names encoded
was defined nowhere. The EVSE type, which IEEE 2030.5 does not define, became
Brick's ``Electric_Vehicle_Charging_Station``. Operation strings
(``soft_cls_building``, ``hard_cls_ev``) and node ids are unchanged. Every
former term is a declared :class:`TermAlias` in :data:`FLEXIBILITY_CAPABILITY`.
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
from gridalyn.twin.semantic.repository import _loads_json
from gridalyn.twin.semantic.vocabulary import (
    CapabilityInputs,
    RelationshipSpec,
    ScenarioCountRule,
    SemanticCapability,
    TermAlias,
)

# ---------------------------------------------------------------------------
# Emitters (moved verbatim from gridalyn/twin/semantic/emitters.py, Phase 21)
# ---------------------------------------------------------------------------


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
                "mapped_from": "flexint:CurtailmentContract",
                "application_scope": "BuildingLevelApplication",
                "flexibility_resource": "thermally_activated_building_system",
            },
        ),
        _node(
            operation_id,
            ["FlexibleOperation", "CurtailmentOperation"],
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
            ["EnergyFlexibility", "CurtailmentFlexibility"],
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
                "contract_type": row.get("contract_type"),
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
            "flexint:describesFlexibility",
            "Gridalyn_Flexint",
            "asset_registry",
            contract_id,
            scenario_id=scenario_id,
        ),
    ):
        builder.add_edge(edge)


def emit_flexibility_asset_nodes(
    builder: SemanticGraphBuilder,
    asset_registry: pd.DataFrame,
) -> None:
    """Emit the flexibility part of the scenario asset registry.

    The EV charging-station nodes, the soft and hard curtailment contracts and
    the EFOnt crosswalk
    from the scenario asset registry. The generic scenario-includes-building
    edges live in the model-first ``emitters.emit_asset_registry``.
    """
    for row in asset_registry.to_dict("records"):
        scenario_id = str(row["scenario_id"])
        building_id = row["building_id"]

        has_ev = bool(row.get("has_ev"))
        ev_id = _safe_str(row.get("ev_id"))
        soft = bool(row.get("soft_cls_participant"))
        hard = bool(row.get("hard_cls_enabled"))

        if has_ev and ev_id:
            builder.add_node(
                _node(
                    ev_id,
                    ["EVSE", "DERAsset"],
                    "brick:Electric_Vehicle_Charging_Station",
                    "Brick",
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
                    f"scenario:{scenario_id}",
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
                    ["CurtailmentContract", "FlexibilityContract"],
                    "flexint:CurtailmentContract",
                    "Gridalyn_Flexint",
                    "asset_registry",
                    contract_id,
                    name=contract_id,
                    scenario_id=scenario_id,
                    properties={
                        "building_id": building_id,
                        "contract_mode": "soft",
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
                    "flexint:participatesIn",
                    "Gridalyn_Flexint",
                    "asset_registry",
                    contract_id,
                    scenario_id=scenario_id,
                ),
                _edge(
                    f"scenario:{scenario_id}",
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
                    ["CurtailmentContract", "FlexibilityContract"],
                    "flexint:CurtailmentContract",
                    "Gridalyn_Flexint",
                    "asset_registry",
                    contract_id,
                    name=contract_id,
                    scenario_id=scenario_id,
                    properties={
                        "ev_id": ev_id,
                        "building_id": building_id,
                        "max_hard_kw": row.get("max_hard_kw"),
                        "contract_mode": "hard",
                        "hard_preferred": hard_preferred,
                    },
                )
            )
            for edge in (
                _edge(
                    ev_id,
                    "ENABLES_CONTRACT",
                    contract_id,
                    "flexint:enablesContract",
                    "Gridalyn_Flexint",
                    "asset_registry",
                    contract_id,
                    scenario_id=scenario_id,
                ),
                _edge(
                    f"scenario:{scenario_id}",
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
                    "flexint:FlexibilityAggregator",
                    "Gridalyn_Flexint",
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
                    "flexint:FlexibilityPortfolio",
                    "Gridalyn_Flexint",
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
                    "flexint:managesPortfolio",
                    "Gridalyn_Flexint",
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
                "flexint:FlexibilityProvider",
                "Gridalyn_Flexint_EFOnt_CIM",
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
                    "Gridalyn_DT_Flexint",
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
                "flexint:FlexibilityOffer",
                "Gridalyn_Flexint",
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
                    "flexint:ConstraintZone",
                    "Gridalyn_Flexint_CIM",
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
                "flexint:aggregates",
                "Gridalyn_Flexint",
                "provider_registry",
                provider_id,
                scenario_id=scenario_id,
            ),
            _edge(
                portfolio_id,
                "INCLUDES_PROVIDER",
                provider_id,
                "flexint:includesProvider",
                "Gridalyn_Flexint",
                "provider_registry",
                provider_id,
                scenario_id=scenario_id,
            ),
            _edge(
                provider_id,
                "OFFERS",
                offer_id,
                "flexint:offers",
                "Gridalyn_Flexint",
                "provider_registry",
                offer_id,
                scenario_id=scenario_id,
            ),
            _edge(
                provider_id,
                "IMPLEMENTS_CONTRACT",
                contract_id,
                "flexint:implementsContract",
                "Gridalyn_Flexint",
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
                    "dt:hasFlexibilityResource",
                    "Gridalyn_DT",
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
                    "flexint:locatedInConstraintZone",
                    "Gridalyn_Flexint",
                    "provider_registry",
                    constraint_zone_id,
                    scenario_id=scenario_id,
                ),
                _edge(
                    offer_id,
                    "TARGETS_CONSTRAINT",
                    constraint_zone_id,
                    "flexint:targetsConstraint",
                    "Gridalyn_Flexint",
                    "provider_registry",
                    constraint_zone_id,
                    scenario_id=scenario_id,
                ),
                _edge(
                    constraint_zone_id,
                    "CONSTRAINT_ZONE_FOR",
                    constraint_id,
                    "flexint:constraintZoneFor",
                    "Gridalyn_Flexint_CIM",
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


def extend_graph_with_flexibility(
    builder: SemanticGraphBuilder,
    asset_registry: pd.DataFrame,
    provider_registry: pd.DataFrame,
) -> None:
    """Apply the flexibility layer to a model-first semantic graph.

    Emits the charging-station, contract and EFOnt nodes and the provider-registry
    ontology. Empty inputs are no-ops, so a project that declares the
    capability but has no flexibility data still builds a valid core graph.

    Args:
        builder: Accumulator that owns node and edge identity.
        asset_registry: Scenario asset registry; empty is a no-op.
        provider_registry: Flexibility provider registry; empty is a no-op.
    """
    if not asset_registry.empty:
        emit_flexibility_asset_nodes(builder, asset_registry)
    if not provider_registry.empty:
        emit_provider_registry(builder, provider_registry)


# ---------------------------------------------------------------------------
# Declaration: vocabulary, axioms and extender, plus its plain-data view
# ---------------------------------------------------------------------------


#: ``flexint:`` is gridalyn's persistent vocabulary for flexibility markets,
#: contracts and agent interaction; ``efont:`` is EFOnt's own published
#: namespace. ``openadr:`` and ``ieee2030_5:`` were removed on 2026-09-11: the
#: first was an invented IRI (the OpenADR Alliance publishes no RDF), the second
#: is not a namespace, and neither carried a term except an EVSE type IEEE
#: 2030.5 does not define.
_FLEXIBILITY_NAMESPACES: dict[str, str] = {
    "efont": "http://www.semanticweb.org/hlee9/ontologies/2021/4/EF-core#",
    "flexint": "https://w3id.org/gridalyn/ontology/flexint#",
}

_FLEXIBILITY_TYPES: tuple[str, ...] = (
    "brick:Electric_Vehicle_Charging_Station",
    "dt:ScenarioDevice",
    "efont:EnergyFlexibility",
    "efont:EnergyFlexibilityKPI",
    "efont:FlexibleLoadCharacteristic",  # Aspirational — not currently emitted.
    "efont:FlexibleOperation",
    "efont:ThermallyActivatedBuildingSystem",
    "flexint:ConstraintZone",
    "flexint:CurtailmentContract",
    "flexint:FlexibilityAggregator",
    "flexint:FlexibilityOffer",
    "flexint:FlexibilityPortfolio",
    "flexint:FlexibilityProvider",
)

_FLEXIBILITY_RELATIONSHIPS: tuple[RelationshipSpec, ...] = (
    RelationshipSpec(
        "AGGREGATES",
        "flexint:aggregates",
        ("flexint:FlexibilityAggregator",),
        ("flexint:FlexibilityProvider",),
    ),
    RelationshipSpec(
        "ALLOWS",
        "efont:allows",
        ("efont:ThermallyActivatedBuildingSystem",),
        ("efont:FlexibleOperation",),
    ),
    RelationshipSpec(
        "CONSTRAINT_ZONE_FOR",
        "flexint:constraintZoneFor",
        ("flexint:ConstraintZone",),
        ("cim:ACLineSegment", "cim:ConnectivityNode", "cim:PowerTransformer"),
    ),
    RelationshipSpec(
        "DESCRIBES_FLEXIBILITY",
        "flexint:describesFlexibility",
        ("flexint:CurtailmentContract",),
        ("efont:EnergyFlexibility",),
    ),
    RelationshipSpec(
        "ENABLES",
        "efont:enables",
        ("efont:FlexibleOperation",),
        ("efont:EnergyFlexibility",),
    ),
    RelationshipSpec(
        "ENABLES_CONTRACT",
        "flexint:enablesContract",
        ("brick:Electric_Vehicle_Charging_Station",),
        ("flexint:CurtailmentContract",),
        note=(
            "Until 2026-09-10 the EVSE-to-Hard-CLS edge shared the label ENABLES "
            "with EFOnt's operation-to-flexibility property while meaning "
            "something else, and carried cls:enables."
        ),
    ),
    RelationshipSpec(
        "HAS_EVSE",
        "dt:hasEVSE",
        ("brick:Building",),
        ("brick:Electric_Vehicle_Charging_Station",),
    ),
    RelationshipSpec(
        "HAS_FLEXIBILITY_RESOURCE",
        "dt:hasFlexibilityResource",
        ("brick:Building", "flexint:FlexibilityProvider"),
        ("dt:ScenarioDevice", "efont:ThermallyActivatedBuildingSystem"),
        note=(
            "One predicate for building-to-EFOnt-resource and provider-to-device "
            "edges; until 2026-09-10 the provider-to-device edges carried "
            "cls:hasFlexibilityResource."
        ),
    ),
    RelationshipSpec(
        "IMPLEMENTS_CONTRACT",
        "flexint:implementsContract",
        ("flexint:FlexibilityProvider",),
        ("flexint:CurtailmentContract",),
        source_cardinality=(1, 1),
    ),
    RelationshipSpec(
        "INCLUDES_ASSET",
        "dt:includesAsset",
        ("dt:Scenario",),
        (
            "brick:Electric_Vehicle_Charging_Station",
            "flexint:CurtailmentContract",
            "flexint:FlexibilityAggregator",
            "flexint:FlexibilityProvider",
        ),
    ),
    RelationshipSpec(
        "INCLUDES_PROVIDER",
        "flexint:includesProvider",
        ("flexint:FlexibilityPortfolio",),
        ("flexint:FlexibilityProvider",),
    ),
    RelationshipSpec(
        "LOCATED_IN_CONSTRAINT_ZONE",
        "flexint:locatedInConstraintZone",
        ("flexint:FlexibilityProvider",),
        ("flexint:ConstraintZone",),
    ),
    RelationshipSpec(
        "MANAGES_PORTFOLIO",
        "flexint:managesPortfolio",
        ("flexint:FlexibilityAggregator",),
        ("flexint:FlexibilityPortfolio",),
        source_cardinality=(1, 1),
    ),
    RelationshipSpec(
        "OFFERS",
        "flexint:offers",
        ("flexint:FlexibilityProvider",),
        ("flexint:FlexibilityOffer",),
        source_cardinality=(1, 1),
    ),
    RelationshipSpec(
        "PARTICIPATES_IN",
        "flexint:participatesIn",
        ("brick:Building",),
        ("flexint:CurtailmentContract",),
    ),
    RelationshipSpec(
        "QUANTIFIES",
        "efont:Quantifies",
        ("efont:EnergyFlexibilityKPI",),
        ("efont:EnergyFlexibility",),
    ),
    RelationshipSpec(
        "TARGETS_CONSTRAINT",
        "flexint:targetsConstraint",
        ("flexint:FlexibilityOffer",),
        ("flexint:ConstraintZone",),
    ),
)

_FLEXIBILITY_SCENARIO_COUNTS: tuple[ScenarioCountRule, ...] = (
    ScenarioCountRule("n_ev", "brick:Electric_Vehicle_Charging_Station"),
    ScenarioCountRule(
        "n_hard_preferred",
        "flexint:CurtailmentContract",
        property_true="hard_preferred",
        property_equals=(("contract_mode", "hard"),),
    ),
    ScenarioCountRule(
        "n_soft_participants",
        "flexint:CurtailmentContract",
        property_equals=(("contract_mode", "soft"),),
    ),
)


#: Predicates for the network-impact surrogate graph, which EFOnt does not
#: define; declared so they are terms with an IRI rather than free strings.
_FLEXIBILITY_PREDICATES: tuple[str, ...] = (
    "flexint:hasNetworkImpact",
    "flexint:providesFlexibility",
)

_MOVED_TO_FLEXINT = (
    "moved from the unresolvable gridalyn.local cls: namespace to the persistent "
    "flexint: namespace, unchanged otherwise"
)
_RENAMED_BY_PREFIX = (
    "ConstraintZone",
    "FlexibilityAggregator",
    "FlexibilityOffer",
    "FlexibilityPortfolio",
    "FlexibilityProvider",
    "aggregates",
    "constraintZoneFor",
    "describesFlexibility",
    "enablesContract",
    "implementsContract",
    "includesProvider",
    "locatedInConstraintZone",
    "managesPortfolio",
    "offers",
    "participatesIn",
    "targetsConstraint",
)
_ONE_CONTRACT_CLASS = (
    "the Soft/Hard distinction is the contract_mode property, not a class; the "
    "acronym the class name encoded was defined nowhere"
)

#: Every term this capability emitted before 2026-09-11 that it no longer
#: emits, each resolvable to its replacement for one release.
_FLEXIBILITY_ALIASES: tuple[TermAlias, ...] = (
    *(
        TermAlias(f"cls:{name}", f"flexint:{name}", note=_MOVED_TO_FLEXINT)
        for name in _RENAMED_BY_PREFIX
    ),
    TermAlias(
        "cls:SoftCLSContract",
        "flexint:CurtailmentContract",
        (("contract_mode", "soft"),),
        note=_ONE_CONTRACT_CLASS,
    ),
    TermAlias(
        "cls:HardCLSContract",
        "flexint:CurtailmentContract",
        (("contract_mode", "hard"),),
        note=_ONE_CONTRACT_CLASS,
    ),
    TermAlias(
        "ieee2030_5:EVSE",
        "brick:Electric_Vehicle_Charging_Station",
        note=(
            "IEEE 2030.5 defines no EVSE type and publishes no RDF namespace; "
            "Brick defines the class"
        ),
    ),
    TermAlias(
        "efont:hasNetworkImpact",
        "flexint:hasNetworkImpact",
        note="EFOnt defines no hasNetworkImpact property",
    ),
    TermAlias(
        "efont:providesFlexibility",
        "flexint:providesFlexibility",
        note="EFOnt defines no providesFlexibility property",
    ),
)


def _extend_from_inputs(
    builder: SemanticGraphBuilder, inputs: CapabilityInputs
) -> None:
    """Adapt the declared extender signature to :func:`extend_graph_with_flexibility`."""
    extend_graph_with_flexibility(
        builder, inputs.asset_registry, inputs.provider_registry
    )


FLEXIBILITY_CAPABILITY = SemanticCapability(
    capability_id="flexibility",
    namespaces=_FLEXIBILITY_NAMESPACES,
    primary_standards={
        "building_flexibility": ("EFOnt",),
        "ev_charging": ("Brick Schema",),
        "flexibility_market": ("gridalyn flexint",),
    },
    semantic_types=_FLEXIBILITY_TYPES,
    relationships=_FLEXIBILITY_RELATIONSHIPS,
    scenario_counts=_FLEXIBILITY_SCENARIO_COUNTS,
    extend=_extend_from_inputs,
    predicates=_FLEXIBILITY_PREDICATES,
    deprecated_aliases=_FLEXIBILITY_ALIASES,
)


def flexibility_profile_extensions() -> dict[str, Any]:
    """Return the flexibility slice of the semantic profile as plain data.

    Derived from :data:`FLEXIBILITY_CAPABILITY`, so this view and the
    declaration cannot drift. The profile a graph is built and validated
    against is composed by
    :func:`~gridalyn.twin.semantic.profile.profile_with_capabilities`.
    """
    capability = FLEXIBILITY_CAPABILITY
    return {
        "namespaces": dict(capability.namespaces),
        "primary_standards": {
            concern: list(standards)
            for concern, standards in capability.primary_standards.items()
        },
        "allowed_semantic_types": list(capability.semantic_types),
        "relationship_types": sorted(spec.name for spec in capability.relationships),
    }


# ---------------------------------------------------------------------------
# Repository queries (moved from gridalyn/twin/semantic/repository.py)
# ---------------------------------------------------------------------------


def query_providers_for_constraint(
    repository: Any,
    constraint_id: str,
    *,
    scenario_id: str | None = None,
) -> tuple[dict[str, Any], ...]:
    """Return flexibility providers located in a constraint zone."""
    zone_ids = _constraint_zone_ids(repository, constraint_id, scenario_id=scenario_id)
    provider_ids: set[str] = set()
    for zone_id in zone_ids:
        provider_ids.update(
            repository.neighbors(
                zone_id,
                "LOCATED_IN_CONSTRAINT_ZONE",
                direction="in",
                scenario_id=scenario_id,
            )
        )
    return tuple(
        _provider_record(repository, provider_id)
        for provider_id in sorted(provider_ids)
        if repository.get_node(provider_id) is not None
    )


def query_trace_building_to_constraint(
    repository: Any,
    building_id: str,
    *,
    scenario_id: str | None = None,
) -> dict[str, Any]:
    """Trace a building to load, bus, providers, and constraint IDs."""
    if repository.get_node(building_id) is None:
        raise KeyError(f"Semantic building node not found: {building_id}")
    load_ids = repository.neighbors(building_id, "HAS_LOAD")
    bus_ids: set[str] = set()
    for load_id in load_ids:
        bus_ids.update(repository.neighbors(load_id, "CONNECTED_TO"))

    providers = _providers_for_building(
        repository, building_id, scenario_id=scenario_id
    )
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


def _constraint_zone_ids(
    repository: Any,
    constraint_id: str,
    *,
    scenario_id: str | None,
) -> tuple[str, ...]:
    zone_ids = set(
        repository.neighbors(
            str(constraint_id),
            "CONSTRAINT_ZONE_FOR",
            direction="in",
            scenario_id=scenario_id,
        )
    )
    zones = repository.nodes.loc[
        repository.nodes["semantic_type"] == "flexint:ConstraintZone"
    ]
    if scenario_id is not None:
        zones = zones.loc[
            zones["scenario_id"].fillna("").astype(str) == str(scenario_id)
        ]
    for _, row in zones.iterrows():
        props = _loads_json(row["properties"])
        if str(props.get("constraint_id")) == str(constraint_id):
            zone_ids.add(str(row["node_id"]))
    return tuple(sorted(zone_ids))


def _providers_for_building(
    repository: Any,
    building_id: str,
    *,
    scenario_id: str | None,
) -> tuple[dict[str, Any], ...]:
    rows = repository.nodes.loc[
        repository.nodes["semantic_type"] == "flexint:FlexibilityProvider"
    ]
    if scenario_id is not None:
        rows = rows.loc[rows["scenario_id"].fillna("").astype(str) == str(scenario_id)]
    providers = []
    for _, row in rows.iterrows():
        record = _provider_record(repository, str(row["node_id"]))
        if record.get("building_id") == building_id:
            providers.append(record)
    return tuple(sorted(providers, key=lambda item: item["provider_id"]))


def _provider_record(repository: Any, provider_id: str) -> dict[str, Any]:
    node = repository.get_node(provider_id)
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


__all__ = [
    "FLEXIBILITY_CAPABILITY",
    "extend_graph_with_flexibility",
    "flexibility_profile_extensions",
]
