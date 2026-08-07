"""Semantic profile definitions for Gridalyn digital-twin graphs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

NAMESPACES = {
    "cim": "https://cim.ucaiug.io/ns#",
    "brick": "https://brickschema.org/schema/Brick#",
    # Aspirational — declared for future/imported use; not currently emitted.
    "s223": "http://data.ashrae.org/standard223#",
    "openadr": "https://openadr.org/ns#",
    "ieee2030_5": "https://standards.ieee.org/ieee/2030.5#",
    "efont": "http://www.semanticweb.org/hlee9/ontologies/2021/4/EF-core#",
    # Aspirational — not currently emitted (Green Button appears only as the
    # source_standard string on dt:TimeSeriesDataset).
    "gb": "https://www.greenbuttondata.org/ns#",
    "cls": "https://gridalyn.local/ontology/cls#",
    "dt": "https://gridalyn.local/ontology/digital-twin#",
}

RELATIONSHIP_TYPES = [
    "AGGREGATES",
    "ALLOWS",
    # Aspirational — declared but not currently emitted by any generator.
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


# Canonical semantic-type vocabulary shared by every generator (the semantic
# graph in mappings.py and the network-impact surrogate). A concept's one
# spelling lives here; generators import it instead of re-declaring divergent
# qnames (Phase 9, finding G10).
SEMANTIC_TYPE: dict[str, str] = {
    "building": "brick:Building",
    "connectivity_node": "cim:ConnectivityNode",
    "energy_consumer": "cim:EnergyConsumer",
    "power_transformer": "cim:PowerTransformer",
    "flexibility_provider": "cls:FlexibilityProvider",
    "scenario": "dt:Scenario",
    "evse": "ieee2030_5:EVSE",
    # Surrogate-specific edge relationship (no semantic-graph counterpart).
    "network_impact": "efont:hasNetworkImpact",
}


def north_america_profile() -> dict[str, Any]:
    """Return the active North America semantic profile."""
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
            # Aspirational — declared but not currently emitted by any generator.
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


def semantic_uri(qname: str) -> str:
    """Resolve a qualified semantic name against the active namespace map."""
    prefix, local_name = qname.split(":", 1)
    return f"{NAMESPACES[prefix]}{local_name}"


def write_profile(path: Path) -> dict[str, Any]:
    """Write the North America profile and return it."""
    profile = north_america_profile()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(profile, f, indent=2, sort_keys=True)
    return profile


__all__ = [
    "NAMESPACES",
    "RELATIONSHIP_TYPES",
    "SEMANTIC_TYPE",
    "north_america_profile",
    "semantic_uri",
    "write_profile",
]
