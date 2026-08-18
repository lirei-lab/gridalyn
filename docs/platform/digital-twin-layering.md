# Digital Twin Layering — Model-First Review & Re-layering Contract

*Phase 21-01 (review/design), 2026-08-17. Evidence-backed read-only audit of
`gridalyn/twin/`, the framework decision, and the re-layering contract that
plans 21-02/21-03 implement. This is the "revisión de la implementación
digital-twin" requested 2026-08-17.*

## Why this document exists

The user asked for a review of the digital-twin implementation with a specific
concern: the twin feels **centered on flexibility when flexibility is only one
of the operations**. The twin should be **model-first** — a first, faithful
representation of the grid model — with **capability layers** (flexibility, EV,
DER, market, …) added on demand, not baked into the core.

This document records the verified diagnosis, the framework decision, and the
re-layering contract. It is the authoritative spec that the execution plans
(`21-02`, `21-03`) implement and `21-04` verifies.

## Verified diagnosis: model-first core, flexibility-biased edges

`gridalyn.twin` is **model-first at its core and flexibility-biased at its
edges**. The coupling to flexibility is **not import-based** — the layer
direction is healthy (`operations`/`simulation` reach into twin only for the
generic `observe_network` state); it is **ontological** — twin restates
operations concepts because knowledge cannot flow downward as an import.

### The model-first core (generic, reusable — keep as-is)

| Subpackage | Evidence | Verdict |
| --- | --- | --- |
| `network/` (model, repository, schema, topology, metadata) | `BASE_TABLE_SCHEMAS` declares roles only — `identity`, `bus`, `from_bus`, `to_bus`, `hv_bus`, `lv_bus`, `load`, `transformer`, `feeder`, `feeder_head_bus`, `feeder_cluster`. Nothing EV/DER/flexibility-specific. | **Generic** |
| `observation/` (contract, ingest, registry) | Schema `(timestamp, entity_id, quantity, value)`; v1 quantity set is exactly `{"voltage_pu": "bus_voltage_pu"}`. No flexibility tags anywhere. The Phase-12 measured-state path is the cleanest model-first example. | **Generic** |
| `adapters/` (network, cim, geojson, authority, registry, validation) | CIM/GeoJSON/authority exports are pure grid equipment. (One leak — see below.) | **Generic (1 leak)** |
| `core/` (graph, ontology) | Generic topology (`PowerGridGraph`). (One hygiene issue — `core/ontology.py` imports `pydantic`, not a declared dependency.) | **Generic (hygiene)** |
| `geoprocess/`, `io/geo.py`, `db/` | GeoJSON processing, pandapower→GeoJSON export, FalkorDB batch mechanism — all domain-agnostic. | **Generic** |

### The four flexibility-biased edges (the re-layering targets)

1. **`twin/semantic/` — the largest concentration.** The default
   `north_america_profile()` declares flexibility/market standards as core
   `primary_standards`: `building_flexibility: EFOnt`, `demand_response:
   OpenADR`, `ev_der_control: IEEE 2030.5`, `cls_market: gridalyn cls
   extension` (`semantic/profile.py:74-82`), and `allowed_semantic_types`
   includes every `cls:*`, `efont:*` and `ieee2030_5:EVSE` type
   (`profile.py:99-118`). `semantic/emitters.py` emits the flexibility
   ontology by default:
   - `_append_efont_soft_cls_crosswalk` (`emitters.py:31`) — EFOnt
     `FlexibilityResource`/`FlexibleOperation`/`EnergyFlexibility` nodes.
   - `_require_provider_columns` (`emitters.py:590`) — **re-declares the
     14-column operations provider schema** with the explicit comment that
     "this contract belongs to the operations layer, which is ABOVE twin; the
     columns are restated here because knowledge cannot flow downward as an
     import".
   - `_emit_provider_aggregates` (`emitters.py:625`), `_emit_provider_offers`
     (`emitters.py:713`), `emit_provider_registry` (`emitters.py:944`) —
     `cls:FlexibilityProvider/Aggregator/Portfolio/Offer/ConstraintZone`.
   - `emit_asset_registry` (`emitters.py:421`) — emits `ieee2030_5:EVSE` /
     `DERAsset` nodes for the EV/CLS asset registry.
   - `semantic/repository.py` exposes flexibility-specific queries
     (`providers_for_constraint`, `trace_building_to_constraint`).
   - `SemanticGraphRepository` has **no in-repo production consumer**; the
     graph's only production consumer is the network-impact surrogate (a
     flexibility feature) and tests.

2. **The default `twin build` is an EV-hosting build.**
   `gridalyn/projects/workflows/digital_twin/build.py` (`build_digital_twin_
   steps`) runs `generate_scenarios` → `ev_scenarios.py`, `generate_ev_
   timeseries`, `run_powerflow` → `run_digital_twin_ev_powerflow.py`,
   `report_transformer_overloads`, `generate_asset_registry`,
   `generate_flexibility_providers`, then the semantic build/validate, and
   (with `--include-network-impact`) the surrogate + locational clearing. The
   `digital_twin` CLI wires `scenarios`/`timeseries` to `ev_scenarios`/
   `ev_timeseries` and lists `*_ev_*` powerflow/verify stages.

3. **`twin/adapters/network.py:557`** — the synthetic producer writes
   `cls_participant: False`, `has_ev: False`, `ev_id: None` into
   `buildings.parquet`. These columns are **not in the declared schema
   contract** (`BASE_TABLE_SCHEMAS`).

4. **`twin/io/timeseries.py`** — EV-specific readers
   (`get_ev_capability_load_all`, `EV_CAPABILITY_MC_FILE =
   "substation_ev_capability_mc.parquet"`); their only production consumer is
   their own test. Orphaned EV-hosting-study IO sitting in the generic twin
   layer.

### Incidental findings

- `twin/core/ontology.py` imports `pydantic`, which is **not** a declared
  `pyproject.toml` dependency (latent dependency-hygiene issue).
- `twin/db/federated_graph_adapter.py` is a generic mechanism (FalkorDB Cypher
  batches from nodes/edges parquet) but operates on the flexibility-tainted
  semantic graph; it is deliberately not on the public facade.

## Framework decision

The framework that best fits "model first, add capability layers by need" is a
**CIM-profile core + AAS-style submodel layers**, which gridalyn already
half-implements.

| Framework | What it contributes | Fit for gridalyn |
| --- | --- | --- |
| **IEC 61970/61968 CIM + CIM Profiles** | The standard grid model: a **generic core** (conducting equipment, topology, measurements) plus **profiles** that restrict/expand the core per use case. | **The core.** gridalyn already adopts "CGMES fields and rules" via `twin/adapters/authority.py` (`ModelProfile`, `ModelAuthoritySet`, `validate_authority_partition`). The profile mechanism exists; it is just not used to gate the semantic graph. |
| **Asset Administration Shell (IEC 63278)** | An asset carries a **mandatory core** plus **optional submodels** (each a capability layer) instantiated only when the use case needs them. | **The layer mechanism.** A feeder/bus/transformer/load is the asset; "flexibility participation", "EV hosting", "DER control" are submodels added on demand. |
| **DTDL v3 (Azure Digital Twins)** | Language-level model-first: `extends` (inheritance) + `Component` (submodel assembly) + **feature extensions** (semantic types/units added per model context). | **The concrete declared-profile mechanism** — a `@context`-style declared profile. Inspiration only; not a runtime dependency. |

**Decision.** Keep the parquet + declared-schema core (it already implements
the CIM core faithfully and cheaply — `rdflib`/RDF serialization stays a
non-goal, per `docs/platform/digital-twin.md`). Add a **declared profile /
capability layer** to the semantic graph using the existing
`foundation/platform/capabilities.py` (`require_capabilities`) and
`twin/adapters/authority.py` (`ModelProfile`) patterns. The generic CIM/Brick
topology emitters stay the model-first default; the CLS/EFOnt/market emitters
move behind an **on-demand semantic capability**. The twin **build** gains a
generic default (network + observation + semantic core) with the EV-hosting
stages becoming a declared `ev-hosting` capability.

### The re-layering contract (what 21-02 / 21-03 implement)

1. **Semantic re-layering (21-02):**
   - The always-on semantic core emits only generic topology/observation types:
     `emit_scenarios`, `emit_buses`, `emit_lines`, `emit_transformers`,
     `emit_premises`, `emit_timeseries_runs` — CIM/Brick/`dt:*` only.
   - A new **on-demand capability** `gridalyn/twin/semantic/capabilities/
     flexibility.py` owns: `_append_efont_soft_cls_crosswalk`, the EVSE/DER
     part of `emit_asset_registry`, `_require_provider_columns`,
     `_emit_provider_aggregates`, `_emit_provider_offers`,
     `emit_provider_registry`, and the flexibility repository queries.
   - The capability is selected through the declared profile (a
     `ModelProfile`-style declaration / `require_capabilities` gate), **never
     an upward import** — the layer direction stays intact.
   - The default `north_america_profile()` primary_standards keep `grid_
     topology` (IEC CIM) and `buildings` (ASHRAE 223 / Brick); the
     flexibility/DR/EV/CLS standards move behind the capability declaration.
2. **Edge-bias removal (21-03):**
   - `adapters/network.py` writes only `BASE_TABLE_SCHEMAS` columns to
     `buildings.parquet`; `cls_participant`/`has_ev`/`ev_id` are removed (the
     flexibility capability derives participation from the declared model, not
     hidden extra columns).
   - `io/timeseries.py` EV readers are retired (no production consumer) or
     moved under the `ev-hosting` capability.
   - The default `twin build` becomes generic (network + observation +
     semantic core); the EV-hosting stages run only when a project declares
     the `ev-hosting` capability.
   - `core/ontology.py` pydantic hygiene fixed (declared in `pyproject.toml`
     or the import removed).
3. **Verification (21-04):** `tests/test_twin_model_first.py` proves the
   generic semantic core emits **zero** `cls:`/`efont:`/`FlexibilityProvider`
   triples; with the capability **ON** the graph is **value-identical** to the
   pre-21-02 graph (R7 by value); the generic build produces
   network+observation+semantic-core artifacts.

## Constraints

- **R7**: flagship/admm baselines value-identical; `projects/*/outputs/`
  untouched; compare by value, not bytes.
- **Layer direction**: twin stays below assets/simulation/operations; the
  capability layer is declared configuration (a profile), not an upward import.
- The network-impact surrogate (the only production consumer of the semantic
  types) keeps identical behavior when the capability is on.
- `SemanticGraphRepository` and `federated_graph_adapter` stay off-facade;
  their generic mechanism is kept, the data they operate on becomes
  profile-scoped.
- **Non-goal (unchanged)**: bidirectional control flow and RDF/XML
  serialization remain out of scope, per `docs/concepts/network-model.md` and
  `docs/platform/digital-twin.md`.

## Declaring a capability on a project

The re-layering is additive and backwards-compatible: **existing callers that
omit a capability set keep the pre-Phase-21 behavior** (the `flexibility`
capability is assumed, R7). A project opts into the model-first core by
declaring its capabilities explicitly.

### Semantic graph (API)

```python
from gridalyn.twin.semantic.mappings import build_semantic_graph

# Model-first core only (no flexibility ontology):
nodes, edges, manifest = build_semantic_graph(
    ..., capabilities=set(),
)

# Model-first core + the flexibility layer (value-identical to pre-Phase-21):
nodes, edges, manifest = build_semantic_graph(
    ..., capabilities={"flexibility"},
)
```

### Semantic graph (workflow script)

The generator script accepts `--semantic-capabilities`:

```bash
# Model-first core only:
gridalyn semantic build --semantic-capabilities

# Core + flexibility (legacy default when the flag is omitted):
gridalyn semantic build --semantic-capabilities flexibility
```

### Twin build

```python
from gridalyn.projects.workflows.digital_twin.build import build_digital_twin_steps

# Generic build (base + building models + semantic core + reports):
build_digital_twin_steps(capabilities=set())

# Full legacy build (ev-hosting + flexibility layers) — the default:
build_digital_twin_steps()
```

### Profile

`profile_with_capabilities({"flexibility"})` returns the merged profile (core +
flexibility extensions); `north_america_profile()` returns the core alone;
`write_profile(path, capabilities=...)` writes the merged one.
