# Digital Twin Layering — Model-First Architecture

The digital twin is **model-first**: its first, faithful representation is the
grid model — a canonical, schema-declared network plus its observation state.
Domain capabilities (flexibility, EV/DER, market) are **layers added on
demand** by declaring a capability in the semantic profile, never baked into
the core. This document records the layering model, the framework decision,
and how to use it.

## The model-first core (always emitted)

The twin core is generic, domain-agnostic grid equipment:

| Subpackage | Responsibility | Domain |
| --- | --- | --- |
| `network/` (model, repository, schema, topology, metadata) | `BASE_TABLE_SCHEMAS` declares roles only — `identity`, `bus`, `from_bus`, `to_bus`, `hv_bus`, `lv_bus`, `load`, `transformer`, `feeder`, `feeder_head_bus`, `feeder_cluster`. Nothing EV/DER/flexibility-specific. | Generic |
| `observation/` (contract, ingest, registry) | Measured-state schema `(timestamp, entity_id, quantity, value)`; v1 quantity set is `{"voltage_pu": "bus_voltage_pu"}`. | Generic |
| `adapters/` (network, cim, geojson, authority, registry, validation) | CIM/GeoJSON/authority exports of pure grid equipment. | Generic |
| `core/` (graph, ontology), `geoprocess/`, `io/geo.py`, `db/` | Generic topology, GeoJSON processing, export, FalkorDB batch mechanism. | Generic |

The model-first semantic core emits only generic CIM/Brick types —
`cim:ConnectivityNode`/`ACLineSegment`/`EnergyConsumer`/`PowerTransformer`,
`brick:Building`, `dt:Scenario`/`SimulationRun`/`TimeSeriesDataset` — and the
generic relationships (`CONNECTS`, `CONNECTED_TO`, `FEEDS`, `HAS_LOAD`,
`INCLUDES_ASSET`, `OBSERVES`, `PRODUCED`).

## Capability layers (added on demand)

A **capability** is a declared semantic layer: it owns the emitters for its
ontology, its profile extensions, and its repository queries. It is declared
configuration (a profile), never an upward import — the layer direction stays
intact, and `operations`/`assets` never import it.

### The flexibility capability

`gridalyn/twin/semantic/capabilities/flexibility.py` is the on-demand
flexibility layer:

- the CLS/EFOnt/market ontology — `cls:SoftCLSContract`/`HardCLSContract`,
  `cls:FlexibilityProvider`/`Aggregator`/`Portfolio`/`Offer`/`ConstraintZone`,
  the EFOnt crosswalk (`FlexibilityResource`, `FlexibleOperation`,
  `EnergyFlexibility`, `EnergyFlexibilityKPI`), and `ieee2030_5:EVSE`/`DERAsset`
  nodes;
- the 14-column operations provider-registry schema re-declaration
  (`_require_provider_columns` — the contract belongs to the operations layer
  above twin, so it is restated here rather than imported downward);
- the flexibility repository queries as free functions
  (`query_providers_for_constraint`, `query_trace_building_to_constraint`).

Its profile extensions (`flexibility_profile_extensions`) supply the
flexibility namespaces/standards/types (`EFOnt`, `OpenADR`, `IEEE 2030.5`,
`cls:`) that the model-first core omits.

## Framework decision

The layering follows a **CIM-profile core + Asset-Administration-Shell
submodel pattern**:

| Layer | Standard | Role |
| --- | --- | --- |
| **Core** | IEC 61970/61968 CIM + CIM Profiles | The standard grid model: a generic core (conducting equipment, topology, measurements) plus profiles that restrict/expand the core per use case. Gridalyn adopts "CGMES fields and rules" via `twin/adapters/authority.py` (`ModelProfile`, `ModelAuthoritySet`, `validate_authority_partition`). |
| **Layer mechanism** | Asset Administration Shell (IEC 63278) | An asset carries a mandatory core plus optional **submodels** (each a capability layer) instantiated only when the use case needs them. A feeder/bus/transformer/load is the asset; "flexibility participation", "EV hosting", "DER control" are submodels added on demand. |
| **Declared-profile mechanism** | DTDL v3 (Azure) | `extends`/`Component`/feature extensions — the idea of declaring a capability as a model context. Inspiration only; not a runtime dependency. |

The parquet + declared-schema core already implements the CIM core faithfully
and cheaply; RDF/XML serialization stays a non-goal (see
`docs/platform/digital-twin.md`). The capability layer uses the existing
`require_capabilities` (`foundation/platform/capabilities.py`) and
`ModelProfile` (`twin/adapters/authority.py`) machinery.

## Using the layers

The layering is additive and backwards-compatible: **callers that omit a
capability set keep the full graph** (the `flexibility` capability is assumed,
so existing study runs are unchanged). A project opts into the model-first
core by declaring its capabilities explicitly.

### Semantic graph (API)

```python
from gridalyn.twin.semantic.mappings import build_semantic_graph

# Model-first core only (no flexibility ontology):
nodes, edges, manifest = build_semantic_graph(
    ..., capabilities=set(),
)

# Model-first core + the flexibility layer:
nodes, edges, manifest = build_semantic_graph(
    ..., capabilities={"flexibility"},
)
```

### Semantic graph (workflow script)

The generator script accepts `--semantic-capabilities`:

```bash
# Model-first core only:
gridalyn semantic build --semantic-capabilities

# Core + flexibility (the default when the flag is omitted):
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

The CLI exposes the same selection for *any* project's twin: `--instance`
names which twin under `instances/<name>/digital_twin/` to build, and
`--capabilities` declares the layers (an empty value is the generic
model-first build; omitting it keeps the legacy `ev-hosting,flexibility`
default):

```bash
uv run gridalyn twin build --instance <name> --capabilities "" --dry-run
uv run gridalyn twin build --instance <name> --capabilities flexibility
```

Layer scripts resolve the instance through `GRIDALYN_INSTANCE` /
`GRIDALYN_WORKSPACE_ROOT`, so the same general scripts materialize on any
declared twin without knowing its path.

### Profile

`profile_with_capabilities({"flexibility"})` returns the merged profile (core +
flexibility extensions); `north_america_profile()` returns the core alone;
`write_profile(path, capabilities=...)` writes the merged one. `semantic_uri`
resolves core + capability namespaces, so a qname emitted by any enabled
capability resolves correctly.
