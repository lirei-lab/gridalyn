"""Semantic profile definitions for Gridalyn digital-twin graphs — the
model-first core.

**Phase 21 re-layering (2026-08-17):** :func:`north_america_profile` is now the
model-first core profile: generic IEC CIM topology, Brick/ASHRAE premises,
scenario and run provenance. The flexibility/market standards
(``building_flexibility``/EFOnt, ``demand_response``/OpenADR,
``ev_der_control``/IEEE 2030.5, ``cls_market``) and their semantic types live
in the on-demand capability
:mod:`gridalyn.twin.semantic.capabilities.flexibility`
(:func:`~gridalyn.twin.semantic.capabilities.flexibility.flexibility_profile_extensions`).
A project that declares the ``flexibility`` capability merges the extensions
over the core so the emitted manifest namespaces/types stay complete (R7:
value-identical to the pre-change profile when the capability is on).

``SEMANTIC_TYPE`` stays the **shared canonical vocabulary** for every generator
(the semantic graph and the network-impact surrogate) — it is a spelling
registry, not an emission bias; the flexibility keys it carries correspond to
the capability.
"""

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
    # Aspirational — not currently emitted (Green Button appears only as the
    # source_standard string on dt:TimeSeriesDataset).
    "gb": "https://www.greenbuttondata.org/ns#",
    "dt": "https://gridalyn.local/ontology/digital-twin#",
}

RELATIONSHIP_TYPES = [
    "CHARACTERIZES",  # Aspirational — not currently emitted.
    "CONNECTS",
    "CONNECTED_TO",
    "FEEDS",
    "HAS_LOAD",
    "INCLUDES_ASSET",
    "OBSERVES",
    "PRODUCED",
]

# Canonical FULL ordering (the pre-Phase-21 insertion order), kept so the
# merged profile with the ``flexibility`` capability reproduces the committed
# artifact byte-for-byte (R7). The core-only profile uses the generic subset
# (``RELATIONSHIP_TYPES`` / the core ``allowed_semantic_types``).
_ALLOWED_SEMANTIC_TYPES_FULL: list[str] = [
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
    "efont:FlexibleLoadCharacteristic",  # Aspirational — not currently emitted.
    "efont:FlexibleOperation",
    "efont:ThermallyActivatedBuildingSystem",
    "ieee2030_5:EVSE",
]

_RELATIONSHIP_TYPES_FULL: list[str] = [
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


# Canonical semantic-type vocabulary shared by every generator (the semantic
# graph in mappings.py and the network-impact surrogate). A concept's one
# spelling lives here; generators import it instead of re-declaring divergent
# qnames (Phase 9, finding G10). The flexibility/DER keys
# (``flexibility_provider``, ``evse``, ``network_impact``) belong to the
# on-demand flexibility capability and are used by the surrogate and the
# capability's emitters, never by the model-first emission default.
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
    """Return the active North America semantic profile (model-first core)."""
    return {
        "semantic_profile": "north_america",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "namespaces": NAMESPACES,
        "primary_standards": {
            "grid_topology": ["IEC CIM", "IEC 61970", "IEC 61968", "CIM100"],
            "buildings": ["ASHRAE 223", "Brick Schema"],
            "metering": ["Green Button", "NAESB ESPI"],
        },
        "allowed_semantic_types": [
            "brick:Building",
            "cim:ACLineSegment",
            "cim:ConnectivityNode",
            "cim:EnergyConsumer",
            "cim:PowerTransformer",
            "dt:Scenario",
            "dt:SimulationRun",
            "dt:TimeSeriesDataset",
        ],
        "relationship_types": RELATIONSHIP_TYPES,
        "unit_conventions": {
            "active_power": "kW or MW, explicit in property name",
            "reactive_power": "kvar or Mvar, explicit in property name",
            "voltage": "kV or pu, explicit in property name",
            "current": "kA, explicit in property name",
        },
        # SAREF is not integrated at all today -- no generator emits a
        # `saref:` type, primary or crosswalk -- so a declared
        # `crosswalk_only_namespaces` constraint had nothing to enforce and
        # no reader checked it (removed 2026-08-19). If SAREF is integrated
        # later, declare and enforce this alongside the real emitter, not
        # ahead of it.
    }


_FLEX_NAMESPACES_CACHE: dict[str, str] | None = None


def _all_namespaces() -> dict[str, str]:
    """Merge the core namespaces with the declared capabilities' namespaces.

    The model-first core owns ``NAMESPACES``; the on-demand capabilities add
    their own (``cls``/``efont``/``ieee2030_5``/``openadr`` for flexibility).
    ``semantic_uri`` must resolve a qname emitted by any enabled capability,
    so it resolves against the merged map (memoized; the capability module is
    lazy-imported so a pure model-first install never touches it).
    """
    global _FLEX_NAMESPACES_CACHE
    if _FLEX_NAMESPACES_CACHE is None:
        from gridalyn.twin.semantic.capabilities.flexibility import (
            flexibility_profile_extensions,
        )

        _FLEX_NAMESPACES_CACHE = flexibility_profile_extensions()["namespaces"]
    return {**NAMESPACES, **_FLEX_NAMESPACES_CACHE}


def semantic_uri(qname: str) -> str:
    """Resolve a qualified semantic name against the active namespace map."""
    prefix, local_name = qname.split(":", 1)
    return f"{_all_namespaces()[prefix]}{local_name}"


def profile_with_capabilities(
    capabilities: set[str] | None = None,
) -> dict[str, Any]:
    """Return the semantic profile for a set of declared capabilities.

    The model-first core profile is the base; each declared capability merges
    its profile extensions over it so the emitted manifest namespaces/types
    stay complete (R7: value-identical to the pre-change profile when the
    ``flexibility`` capability is on).

    Args:
        capabilities: Declared semantic capabilities. ``None`` preserves the
            pre-Phase-21 profile (``flexibility`` assumed, for existing
            callers); an explicit set is the model-first contract.

    Returns:
        The merged profile dict.
    """
    capabilities = {"flexibility"} if capabilities is None else set(capabilities)
    profile = north_america_profile()
    if "flexibility" in capabilities:
        from gridalyn.twin.semantic.capabilities.flexibility import (
            flexibility_profile_extensions,
        )

        extensions = flexibility_profile_extensions()
        profile["namespaces"] = {**profile["namespaces"], **extensions["namespaces"]}
        profile["primary_standards"] = {
            **profile["primary_standards"],
            **extensions["primary_standards"],
        }
        # Preserve the canonical FULL ordering (pre-Phase-21 insertion order)
        # so the merged profile is byte-identical to the committed artifact
        # when the capability is on (R7) — do not re-sort.
        profile["allowed_semantic_types"] = list(_ALLOWED_SEMANTIC_TYPES_FULL)
        profile["relationship_types"] = list(_RELATIONSHIP_TYPES_FULL)
    return profile


def write_profile(
    path: Path,
    capabilities: set[str] | None = None,
) -> dict[str, Any]:
    """Write the North America profile and return it.

    Args:
        path: Destination for the profile JSON.
        capabilities: Declared semantic capabilities; merged over the core
            profile (see :func:`profile_with_capabilities`).

    Returns:
        The written profile dict.
    """
    profile = profile_with_capabilities(capabilities)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(profile, f, indent=2, sort_keys=True)
    return profile


__all__ = [
    "NAMESPACES",
    "RELATIONSHIP_TYPES",
    "SEMANTIC_TYPE",
    "north_america_profile",
    "profile_with_capabilities",
    "semantic_uri",
    "write_profile",
]
