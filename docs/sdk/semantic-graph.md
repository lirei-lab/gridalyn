# Semantic Graph SDK

The semantic graph SDK maps Gridalyn artifacts into ontology-aligned nodes and
edges. The graph is a relationship index over model artifacts, not a replacement
for Parquet time-series analytics.

## Current Profile

The North America profile uses:

- CIM for grid topology;
- ASHRAE 223 and Brick for buildings;
- Green Button/ESPI for customer interval metadata;
- OpenADR for demand response and flexibility event semantics;
- IEEE 2030.5 for future DER/EV control alignment;
- Gridalyn/CLS extensions for concepts not covered cleanly by standards.

## SDK Duties

- build nodes and edges from canonical artifacts;
- validate relationship endpoints;
- preserve source IDs and semantic types;
- answer operational relationship queries from the materialized graph;
- prepare migration to FalkorDB or compatible graph stores.

## Query Repository

Use `SemanticGraphRepository` when application or workflow code needs graph
answers instead of raw node and edge tables:

```python
from gridalyn.twin import SemanticGraphRepository

repo = SemanticGraphRepository.from_parquet("instances/default/digital_twin/semantic")
providers = repo.providers_for_constraint("transformer:64", scenario_id="S4")
trace = repo.trace_building_to_constraint("building:123", scenario_id="S4")
```

The repository keeps the semantic graph useful without making it the numerical
source of truth. Parquet reports and time-series remain the analytical layer;
the graph answers relationship questions such as which providers target a
constraint, which assets belong to a scenario, or how a building traces to a
network zone.

See [Semantic Model And Graph](../semantic-layer/semantic-graph.md).
