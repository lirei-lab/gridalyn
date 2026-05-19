# Network Model

The network model is the center of the platform. Inspired by utility platforms
such as Evolve, Gridalyn treats topology and equipment identity as durable
concepts rather than temporary simulation tables.

## Core Objects

| Concept | Meaning |
| --- | --- |
| Connectivity node / bus | Electrical connection point used by topology, powerflow, and semantic graph layers. |
| Line segment | Conducting path between nodes. |
| Transformer | Equipment that connects voltage levels and often defines local operational constraints. |
| Building / energy consumer | Demand-side asset connected to the network. |
| EVSE / DER asset | Controllable or semi-controllable asset associated with a building or connection point. |
| Feeder / zone | Network grouping used for partial model access, operations, and visualization. |

## Why It Matters

Network-aware operations require knowing where assets are connected. Flexibility
providers should not be selected only by price or aggregate capacity; they must
also be evaluated against the topology, affected transformers, voltage risk,
thermal loading, and downstream grouping.

## Current Implementation

- Static assets are materialized in `digital_twin/base`.
- Scenario participation is materialized in `digital_twin/scenarios`.
- Topology-aware provider and network-impact artifacts are materialized in
  `digital_twin/flexibility`.
- Ontology-aligned relationships are materialized in `digital_twin/semantic`.
- Python access is exposed through `gridalyn.twin` and cross-cutting
  `gridalyn.foundation` helpers.

## Target Direction

Gridalyn should continue moving toward partial model access by feeder,
transformer, connection zone, and scenario state. That is the path from
research workflow to utility-grade platform behavior.
