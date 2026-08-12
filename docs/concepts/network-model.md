# Network Model

The network model is the center of the platform. Inspired by utility platforms
such as Evolve, Gridalyn treats topology and equipment identity as durable
concepts rather than temporary simulation tables.

## What Class of Thing This Is

The package is called `gridalyn.twin`, and that name is **aspirational**. Under
Kritzinger's taxonomy — the one the literature actually uses — the three classes
are separated by *automated data flow*, not by fidelity:

| Class | Defining property |
| --- | --- |
| Digital **model** | No automated data exchange with a physical counterpart. |
| Digital **shadow** | Automated one-way flow, physical → digital. |
| Digital **twin** | Automated flow in **both** directions. |

Measured against that, `gridalyn.twin` is a **digital model with provenance, a
declared schema, and a place for a clock**. It is not yet a shadow, and it is
certainly not a twin. Specifically:

- It **has** durable identity (`ModelIdentity`, a content-addressed
  `model:sha256:…` version id carrying CGMES `FullModel` semantics), a declared
  column contract that makes an absent artifact distinguishable from an intact
  one, model authority sets that say which producer owns which artifact, and an
  `as_of` field on observed state.
- It **does not** have any automated path that carries measurements from a
  physical feeder into the model. Every `NetworkObservation` in the repository
  today is read off a *solved pandapower network* — a simulation result, not a
  measurement — and all **13** production `observe_network(...)` call sites
  correctly pass `as_of=None`, because none of them has a real instant to offer.

### What would move it to the next class

Exactly one thing: an ingest path that reads a real measurement stream and joins
it to the model's `building_id` / `bus_id` namespace, stamping `as_of` from the
measurement's own timestamp. The seam is already cut — `as_of` is keyword-only
and caller-supplied, and `AS_OF_ABSENT_REASON` travels with the field to say why
it is empty. What is missing is not code but a **key**: the candidate dataset
(`datasets/hq`) is 35,041 × 1000 with columns `'0'`…`'999'`, anonymous ordinals
with nothing joining them to a building. Binding a home to a building would
invent the join rather than measure it, so the producer is deliberately deferred
and no state-producer registry was built.

Bidirectional flow — writing control actions back to physical equipment — is a
recorded **non-goal**, not an omission.

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

- One canonical in-memory type, `NetworkModel`. The former `NetworkSnapshot` was
  **deleted**, not aliased — both source adapters return `NetworkModel`, which
  absorbed `source_adapter`, `source_standard` and `write_parquet`.
- Observed state lives in the same layer as the model it describes:
  `gridalyn.twin.observation` owns `NetworkObservation` and `observe_network`.
  `gridalyn.simulation.observation` remains as a deprecated re-export that
  re-binds the same objects and emits a `DeprecationWarning`.
- Static assets are materialized in `instances/default/digital_twin/base`.
- Scenario participation is materialized in `instances/default/digital_twin/scenarios`.
- Topology-aware provider and network-impact artifacts are materialized in
  `instances/default/digital_twin/flexibility`.
- Ontology-aligned relationships are materialized in `instances/default/digital_twin/semantic`.
- Python access is exposed through `gridalyn.twin` and cross-cutting
  `gridalyn.foundation` helpers.

## Target Direction

Gridalyn should continue moving toward partial model access by feeder,
transformer, connection zone, and scenario state. That is the path from
research workflow to utility-grade platform behavior.
