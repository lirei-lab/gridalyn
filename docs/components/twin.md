# Twin

## What problem this layer solves

Every layer above this one — assets, simulation, operations — needs one
trustworthy answer to "what does the grid look like right now, and where did
that answer come from." `twin` is that answer: a canonical network model with
a declared schema, a stamped identity, and a contract for how observed state
enters it. It does not run power flow and it does not model buildings; it
holds the topology and state that everything else reasons about.

**The name is aspirational, and this page says so on purpose.** Under
Kritzinger's digital-twin taxonomy — a classification of *digital
model / digital shadow / digital twin* by how data moves between the
physical and digital sides, not by how detailed either one is — the
classes are separated by *automated data flow*, not by fidelity. What `gridalyn.twin` ships today is a **canonical,
identified, schema-declared digital model** with a one-way, automated
measured-state **ingest** path: physical → digital only. A *deployment*
becomes a digital **shadow** the moment its operator feeds it real measured
data through that path — the SDK itself never claims to be one, because both
producers it exercises in CI remain simulated-or-fixture. Bidirectional flow
(digital → physical control) is a recorded non-goal. Never write that this
layer "is a digital shadow" unqualified.

## The vocabulary

- **The base** — five canonical tables (`buildings`, `grid_buses`,
  `grid_lines`, `grid_transformers`, `building_grid_connectivity`), each with a
  schema declared in `twin/network/schema.py` (`BASE_TABLE_SCHEMAS`) rather
  than guessed at read time from whatever columns happen to be present. An
  absent artifact fails loudly; it does not silently validate as intact.
- **`ModelIdentity`** — three fields that carry real CGMES `FullModel` header
  semantics (`id` from the model's content digest, `created` from the manifest,
  `profile` from the declared profile id), and two fields deliberately *not*
  claimed as CGMES mappings because the values they hold don't honor those
  fields' meaning (`artifact_paths`, `governance_schema_version`) — named for
  what they actually are rather than for a CGMES field they only resemble.
- **`ModelAuthoritySet` / `ModelProfile`** (`twin/adapters/authority.py`) — the
  CGMES Model Authority Set and profile pattern expressed as *fields and rules
  over parquet*, never as RDF/XML serialization. A profile's dependencies are
  **derived** from `BASE_TABLE_SCHEMAS`'s column references, not hand-declared,
  so they cannot drift out of sync with the schema.
- **`NetworkObservation`** — a reading of network state with a **required**
  `provenance: Literal["simulated", "measured"]` field and an `as_of` instant.
  Two producers resolve by explicit ID through
  `twin/observation/registry.py`, never by `entry_points` auto-discovery:

  | Producer ID | Provenance | Reads |
  | --- | --- | --- |
  | `powerflow` | `simulated` | A solved network's `res_bus`/`res_line` result tables; one observation per solved operating point |
  | `measured-ingest` | `measured` | Tidy `(timestamp, entity_id, quantity, value)` rows against a declared `EntityJoin`; `as_of` stamped **from the datum** — naive timestamps are rejected, never silently localized |

## The contract

A declared schema is a promise, not a suggestion: `validate_authority_partition`
runs at the top of every producer's `load_snapshot()` and checks that the
declared authority sets actually partition the canonical artifacts — no table
claimed twice, none left unclaimed. Reading the base through
`NetworkModelRepository` means every table comes back schema-validated, with
row counts and a SHA-256 per artifact recorded for provenance, not a bag of
whatever columns a producer happened to write.

**Which state a snapshot is read as.** A snapshot's operational state is
declared, never inferred from its contents: `base`, `normal`, `current`,
`planned` or `study_case`. `NetworkModelRepository` resolves exactly one of them
for every model it loads, in a fixed order of authority — an explicit
`operational_state=` passed to the repository wins; failing that, the
`operational_state` recorded in the snapshot's `metadata.json`; failing that,
`base` — the state a snapshot reads as when neither the caller nor the manifest
declares one. A non-`base` state reaches disk exactly one way, through
`write_base_metadata(..., operational_state=...)`; no production adapter passes
it yet, so the manifests they write record no state at all. That absence is not
an error: a manifest carrying no such key — written before the key existed, or
by a producer never told which state it is exporting — loads as `base` rather
than failing, so an older base snapshot keeps reading with no call-site change.
A manifest recording anything outside those five is rejected, naming the
manifest path and the valid set, rather than quietly degraded to `base`; the
same set is enforced at the writer, so an unloadable state cannot reach a file
in the first place. The state belongs to a repository's *reading* of a
snapshot, not to the tables themselves: a `NetworkModel` a source adapter
builds directly in memory carries `operational_state` of `None`, because
nothing has declared which state it represents.

**Why no `rdflib`.** CGMES semantics are adopted as *fields and rules*, never
as *serialization*. `rdflib` is not a dependency of this repository — not in
`pyproject.toml`, in any extra, and real imports of it under `gridalyn/` are
pinned at zero by an AST scan. Its only historical consumer was a dead RDF/XML
exporter with no importers and no tests, removed with the evidence recorded.
Re-adding it to serialize the twin would be a regression, not a feature.

## Using it

Reading the committed base and its identity:

```python
from pathlib import Path
from gridalyn.twin import NetworkModelRepository

repository = NetworkModelRepository(Path("instances/default/digital_twin/base"))
model = repository.load_model()
print(len(model.buildings), "buildings")
print(model.identity.id[:16], model.identity.created)
```
```text
3235 buildings
model:sha256:0b4 2026-08-12T14:10:53.931227+00:00
```

Producing an observation — the two producers share one contract, so calling
code does not need to know which one it is talking to beyond the ID:

```python
from gridalyn.twin.observation.registry import default_observation_producer_registry

registry = default_observation_producer_registry()
for descriptor in registry.list_descriptors():
    print(descriptor.producer_id, descriptor.provenance, descriptor.summary)
```

## Verifying it

```bash
python3 -c "
from gridalyn.twin.network.schema import BASE_TABLE_SCHEMAS
print(sorted(BASE_TABLE_SCHEMAS))"
```
```text
['building_grid_connectivity', 'buildings', 'grid_buses', 'grid_lines', 'grid_transformers']
```

```bash
python3 -c "
from gridalyn.twin.observation.registry import default_observation_producer_registry
for d in default_observation_producer_registry().list_descriptors():
    print(d.producer_id, '->', d.provenance)"
```
```text
measured-ingest -> measured
powerflow -> simulated
```

Both outputs above were produced by running these exact commands against this
repository — not recalled from memory — which is the standard every code
example on this page is held to.

## Where this sits

`twin` sits directly on [Foundation](foundation.md): every table it reads
comes back through the report contract and workspace layout that layer
defines, and every optional adapter it might need — `lightsim2grid`,
`osmnx` — goes through `require_capabilities` before use. What builds on
`twin` is [Assets](assets.md): the buildings, EVs and DER that the network
model's `buildings` and `building_grid_connectivity` tables anchor to bus and
transformer identities.
