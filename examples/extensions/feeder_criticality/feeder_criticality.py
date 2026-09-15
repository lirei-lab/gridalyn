"""Feeder criticality: an example semantic capability shipped as an extension.

The capability lives OUTSIDE gridalyn and reaches a study through the declared
extension path (bd 4ky.8): it is an entry point in the ``gridalyn.extensions``
group whose descriptor declares the role ``semantic_capability``. A study that
lists it in ``spec.inputs.extensions`` gets the capability in its semantic graph;
a study that does not cannot build a graph asking for it -- the build fails
naming the capabilities that are registered.

What it adds is deliberately small, because the point is the mechanism, not the
metric: one assessment per distribution transformer, linked to the transformer
it assesses and carrying how many buildings that transformer serves.

The node and edge records are plain dicts in the columns
``docs/reference/semantic-graph.md`` documents. The graph builder resolves each
``semantic_uri`` from the composed profile, so an extension needs no private
gridalyn helper to emit them.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from gridalyn.foundation.platform.extensions import ExtensionDescriptor
from gridalyn.twin.semantic.vocabulary import (
    CapabilityInputs,
    RelationshipSpec,
    SemanticCapability,
)

if TYPE_CHECKING:
    from gridalyn.twin.semantic.builder import SemanticGraphBuilder

#: The extension's ID: the entry-point name a study declares.
EXTENSION_ID = "feeder_criticality"

#: The semantic capability ID a study's build asks for.
CAPABILITY_ID = "feeder_criticality"

#: An example namespace. Not a persistent identifier: nothing resolves it.
NAMESPACE = "https://example.org/gridalyn-examples/feeder-criticality#"

ASSESSMENT_TYPE = "crit:CriticalityAssessment"
ASSESSES_RELATIONSHIP = "ASSESSES_CRITICALITY"
ASSESSES_PREDICATE = "crit:assessesCriticality"

#: A transformer serving at least this many buildings is assessed ``high``.
HIGH_CRITICALITY_BUILDINGS = 2

_SOURCE_STANDARD = "Example_FeederCriticality"
_SOURCE_TABLE = "grid_transformers"


def _assessment_node(transformer_id: str, building_count: int) -> dict[str, Any]:
    """Return the assessment node of one transformer."""
    return {
        "node_id": f"criticality:{transformer_id}",
        "labels": "CriticalityAssessment",
        "semantic_type": ASSESSMENT_TYPE,
        "semantic_uri": ASSESSMENT_TYPE,
        "source_standard": _SOURCE_STANDARD,
        "source_table": _SOURCE_TABLE,
        "source_id": transformer_id,
        "name": f"criticality of {transformer_id}",
        "scenario_id": None,
        "properties": json.dumps(
            {
                "transformer_id": transformer_id,
                "downstream_building_count": building_count,
                "criticality": (
                    "high" if building_count >= HIGH_CRITICALITY_BUILDINGS else "normal"
                ),
            },
            sort_keys=True,
        ),
    }


def _assesses_edge(transformer_id: str) -> dict[str, Any]:
    """Return the edge from a transformer's assessment to the transformer."""
    source = f"criticality:{transformer_id}"
    return {
        "edge_id": f"{source}|{ASSESSES_RELATIONSHIP}|{transformer_id}",
        "source_id": source,
        "target_id": transformer_id,
        "relationship_type": ASSESSES_RELATIONSHIP,
        "semantic_uri": ASSESSES_PREDICATE,
        "source_standard": _SOURCE_STANDARD,
        "source_table": _SOURCE_TABLE,
        "scenario_id": None,
        "properties": json.dumps({"source_id": transformer_id}, sort_keys=True),
    }


def emit_criticality(builder: SemanticGraphBuilder, inputs: CapabilityInputs) -> None:
    """Emit one assessment per transformer, counting the buildings it serves.

    Args:
        builder: The graph under construction.
        inputs: The canonical twin tables; ``transformers`` and ``buildings``
            are read.
    """
    buildings = inputs.buildings
    served = (
        buildings.groupby("lv_bus_id").size().to_dict() if not buildings.empty else {}
    )
    for row in inputs.transformers.sort_values("transformer_id").itertuples(
        index=False
    ):
        transformer_id = str(row.transformer_id)
        count = int(served.get(row.lv_bus_id, 0))
        builder.add_node(_assessment_node(transformer_id, count))
        builder.add_edge(_assesses_edge(transformer_id))


#: The capability this extension contributes.
CAPABILITY = SemanticCapability(
    capability_id=CAPABILITY_ID,
    namespaces={"crit": NAMESPACE},
    primary_standards={"asset_criticality": ("gridalyn example extension",)},
    semantic_types=(ASSESSMENT_TYPE,),
    relationships=(
        RelationshipSpec(
            ASSESSES_RELATIONSHIP,
            ASSESSES_PREDICATE,
            (ASSESSMENT_TYPE,),
            ("cim:PowerTransformer",),
            source_cardinality=(1, 1),
        ),
    ),
    extend=emit_criticality,
)

#: What the engine records in run provenance.
descriptor = ExtensionDescriptor(
    extension_id=EXTENSION_ID,
    role="semantic_capability",
    name="Feeder criticality (example)",
    version="0.1.0",
    contract_version="1",
)


def factory() -> SemanticCapability:
    """Return the semantic capability this extension contributes.

    Returns:
        The capability declaration, registered by the role router when a study
        declares this extension.
    """
    return CAPABILITY
