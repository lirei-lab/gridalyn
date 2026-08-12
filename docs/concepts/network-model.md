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
  `model:sha256:…` version id; three of its six fields carry CGMES
  `FullModel` header semantics and two deliberately claim none), a declared
  column contract that makes an absent artifact distinguishable from an intact
  one, model authority sets that say which producer owns which artifact, and an
  `as_of` field on observed state.
- It **does not** have any automated path that carries measurements from a
  physical feeder into the model. Every `NetworkObservation` in the repository
  today is read off a *solved pandapower network* — a simulation result, not a
  measurement — and all **13** production `observe_network(...)` call sites
  correctly pass `as_of=None`, because none of them has a real instant to offer.

### What would move it to the next class

Exactly one thing: an ingest path that stamps `as_of` from a real producer's own
timestamp and joins its readings to the model's `building_id` / `bus_id`
namespace. The seam is already cut — `as_of` is keyword-only and
caller-supplied, and `AS_OF_ABSENT_REASON` travels with the field to say why it
is empty. What is missing is the producer on the other side of that seam.

**The producer will be the synthetic generator plus the weather system, not a
measured dataset.** The generator already supplies both things the seam needs,
by construction rather than by inference: a real tz-aware 15-minute
`DatetimeIndex`, and a `unit_000…` → bus join that
`gridalyn.assets.datagen` builds itself. It even computes a usable instant and
throws it away — `coincident_peak_loads_mw` collapses the profile frame with
`per_bus.loc[per_bus.sum(axis=1).idxmax()]`, and that `idxmax()` is a genuine
`Timestamp` (measured `2023-12-18 20:00:00-05:00` on a 12-unit cold day)
discarded on the next line. `as_of` for that snapshot does not need inventing;
it needs *not discarding*.

**Why not `datasets/hq`.** The real Hydro-Québec 1000-home set was the original
candidate and is **disqualified on distribution**, which is the decisive
constraint: the directory is 544 MB, git-ignored, and outside `pyproject.toml`'s
`include = ["gridalyn*"]`, so it cannot ship in the package. A producer whose
only data source cannot be distributed is dead for everyone who installs
Gridalyn from PyPI — it would be an SDK capability that exists in one working
copy and nowhere else. A second problem, that the set's columns are anonymous
ordinals `'0'`…`'999'` with no key joining a home to a building, made the branch
*hard to build*; distribution makes it **wrong to build**, and would still
disqualify it if the join key appeared tomorrow.

HQ keeps the role it already has and is good at: an offline validation reference
for the generators — the all-electric n=215 subset documented in
`projects/ev_hosting_flex/CALIBRATION.md` — run by an operator, never a runtime
dependency.

The producer is therefore deliberately deferred, and no state-producer registry
was built: one real producer plus a placeholder is the speculative abstraction
the platform's registries exist to avoid.

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
