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

Measured against that, `gridalyn.twin` is a **canonical, identified,
schema-declared digital model** — and, since Phase 12 (2026-08-13), the SDK
ships the **measured-state ingest path**: automated one-way physical → digital
flow. A *deployment* becomes a digital shadow when a user feeds that path
their own measured data. The layer itself, as shipped, is not a shadow
unqualified — the SDK cannot ship measured data — and it is not a twin.
Specifically:

- It **has** durable identity (`ModelIdentity`, a content-addressed
  `model:sha256:…` version id; three of its six fields carry CGMES
  `FullModel` header semantics and two deliberately claim none), a declared
  column contract that makes an absent artifact distinguishable from an intact
  one, model authority sets that say which producer owns which artifact, and an
  `as_of` field on observed state.
- It **has** two real producers of the observation contract, distinguished by
  the required `provenance` field and resolved by explicit ID through
  `gridalyn.twin.observation.registry`: `powerflow` (wraps `observe_network`,
  stamps `"simulated"` — it reads a *solved pandapower network*, and its call
  sites correctly pass `as_of=None` because a solver result carries no real
  instant) and `measured-ingest` (`read_measured_observations`, stamps
  `"measured"` and `as_of` **from the datum**).
- It **does not** carry measured data of its own. Both producers the SDK
  itself exercises in CI remain simulated-or-fixture; the measured path at
  scale is operator-receipted (protocol `measured-state-ingest`).

### The ingest path that makes a deployment a shadow

Phase 11 identified exactly one missing thing: an ingest path that stamps
`as_of` from a real producer's own timestamp and joins its readings to the
model's declared bus namespace. Phase 12 built it, in
`gridalyn.twin.observation.ingest`:

- **A declared measurement schema** — `(timestamp, entity_id, quantity,
  value)` rows, following `twin/network/schema.py`'s declared-contract pattern
  rather than inventing a second one. The v1 quantity set is `voltage_pu` →
  `bus_voltage_pu`; an unknown quantity fails loudly naming the supported set.
- **`as_of` stamped from the datum, never inferred.** Naive timestamps are
  rejected, not localized — localizing would manufacture evidence, the exact
  failure mode `AS_OF_ABSENT_REASON` exists to prevent.
- **A user-supplied declared entity join** (`EntityJoin`, `entity_id →
  bus_id`) — configuration, never inference. An entity absent from the join
  fails loudly with a located, remediating error.
- **Loaders** (`load_measurements`) for CSV and parquet; validation lives once,
  in the reader.
- **A producer registry** (`ObservationProducerRegistry`,
  `default_observation_producer_registry()`) with the two producers above —
  explicit IDs, no `entry_points`. Phase 11 correctly declined a registry for
  a single implementation; Phase 12 did not decline one for two.

The honest boundary: CI proves value-level correctness of the ingest on
fixtures (`tests/test_measured_ingest.py`); the at-scale run over real
measured timestamps and entities is operator-verified and recorded as the
`measured-state-ingest` receipt in
`docs/development/verification-receipts.json` — with its synthesis disclosure
stated in the receipt itself (the reference dataset carries no voltage
channel, so the proof's voltage *values* were synthesized; the claim is
mechanics-at-scale on real measured timestamps and entities, never "real
voltage data").

**Why `datasets/hq` is not the shipped producer's data source.** The real
Hydro-Québec 1000-home set is **disqualified on distribution**, which is the
decisive constraint: the directory is 544 MB, git-ignored, and outside
`pyproject.toml`'s `include = ["gridalyn*"]`, so it cannot ship in the
package. A producer whose only data source cannot be distributed is dead for
everyone who installs Gridalyn from PyPI. A second problem, that the set's
columns are anonymous ordinals `'0'`…`'999'` with no key joining a home to a
building, is answered for the shipped path by `EntityJoin` — the join is
declared by the user, never invented. HQ keeps the role it already has and is
good at: an offline validation reference for the generators — the all-electric
n=215 subset documented in `projects/ev_hosting_flex/CALIBRATION.md` — plus
the operator-side scale proof above, run by an operator, never a runtime
dependency.

Bidirectional flow — writing control actions back to physical equipment —
remains a recorded **non-goal**, not an omission.

### Provenance (breaking change, Phase 12)

`NetworkObservation` now **requires** a `provenance` field —
`ObservationProvenance = Literal["simulated", "measured"]` — so a consumer
holding only the object can tell a simulation result from a measurement. There
is deliberately no default: a default would silently mislabel every direct
construction that predates the field. Any code constructing `NetworkObservation`
directly must now pass one; construction without it is a `TypeError`.
`observe_network` stamps `"simulated"` unconditionally, because it reads solver
results, and `drop_missing` carries the value through unchanged. The precedent
for shipping a required-field addition documented rather than slipped in is
`NetworkExportResult.identity` (Phase 11).

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
  `gridalyn.twin.observation` owns `NetworkObservation`, `observe_network`,
  the measured-state ingest (`read_measured_observations`, `load_measurements`,
  `EntityJoin`) and the producer registry
  (`default_observation_producer_registry`).
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
