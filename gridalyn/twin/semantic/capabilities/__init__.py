"""On-demand semantic graph capabilities.

The default semantic graph is model-first: it emits only generic CIM/Brick
topology, premises, scenarios and run provenance. Domain capabilities live here
as **on-demand layers**. Each is a
:class:`~gridalyn.twin.semantic.vocabulary.SemanticCapability` declaration --
namespaces, types, relationships with their axioms, scenario count rules, and
an extender -- resolved by explicit ID through
:mod:`gridalyn.twin.semantic.registry`. The registry, not an ``if`` in the
orchestrator, decides what a declared name means, and an unregistered name
raises. None of them may be reached by an upward import: a capability is
declared configuration, never imported by ``operations``.

Current capabilities:

* :mod:`gridalyn.twin.semantic.capabilities.flexibility` — the CLS/EFOnt/market
  ontology (SoftCLS/HardCLS contracts, flexibility providers/aggregators/
  portfolios/offers/constraint zones, EFOnt crosswalk, IEEE 2030.5 EVSE/DER
  nodes) plus the flexibility-specific repository queries.
"""

from __future__ import annotations

from gridalyn.twin.semantic.capabilities.flexibility import (
    FLEXIBILITY_CAPABILITY,
    extend_graph_with_flexibility,
)

__all__ = ["FLEXIBILITY_CAPABILITY", "extend_graph_with_flexibility"]
