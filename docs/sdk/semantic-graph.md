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
- prepare migration to FalkorDB or compatible graph stores.

See [Semantic Model And Graph](../semantic-layer/semantic-graph.md).
