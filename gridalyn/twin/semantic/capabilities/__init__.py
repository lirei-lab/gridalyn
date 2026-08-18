"""On-demand semantic graph capabilities (Phase 21 model-first re-layering).

The default semantic graph is model-first: it emits only generic CIM/Brick
topology, premises, scenarios and run provenance. Domain capabilities
(flexibility, EV/DER, market) live here as **on-demand layers** that a project
declares through its semantic profile. Each capability extends the graph with
its own emitters and profile extensions; none of them may be reached by an
upward import (the layer direction stays intact — a capability is declared
configuration, never imported by `operations`).

Current capabilities:

* :mod:`gridalyn.twin.semantic.capabilities.flexibility` — the CLS/EFOnt/market
  ontology (SoftCLS/HardCLS contracts, flexibility providers/aggregators/
  portfolios/offers/constraint zones, EFOnt crosswalk, IEEE 2030.5 EVSE/DER
  nodes) plus the flexibility-specific repository queries. Constructed only
  when a project declares the ``flexibility`` semantic capability.
"""

from __future__ import annotations

from gridalyn.twin.semantic.capabilities.flexibility import (
    extend_graph_with_flexibility,
)

__all__ = ["extend_graph_with_flexibility"]
