# Semantic Graph

The semantic graph is a federated index over the existing digital twin data. It
does not replace Parquet as the analytical source of truth. Instead, it adds
stable entity IDs, ontology labels, relationship metadata, and validation reports
so the same assets can be queried as a graph and later migrated to FalkorDB.

## North America Profile

The active profile is:

```text
instances/default/digital_twin/semantic/profile_north_america.json
```

The profile is North America-first and **model-first**: the core profile
carries the generic grid model, and the flexibility/market ontology is an
**on-demand capability** a project declares through its semantic profile
(`build_semantic_graph(capabilities=...)` / `--semantic-capabilities` — see
`docs/platform/digital-twin-layering.md`).

Core (always emitted):

- IEC CIM / IEC 61970 / IEC 61968 for grid topology;
- CIM100 and GridAPPS-D-compatible distribution extensions where needed;
- ASHRAE 223 and Brick for buildings, points, meters, and building systems;
- Green Button / NAESB ESPI for customer interval metadata.

Flexibility capability (`capabilities={"flexibility"}`, on-demand):

- LBNL Energy Flexibility Ontology (EFOnt) for building flexibility resources,
  flexible operations, load characteristics, and flexibility KPIs;
- OpenADR for demand-response and CLS event messaging;
- IEEE 2030.5 reserved for future DER and EV control interoperability;
- `cls:` as the local namespace for Soft CLS and Hard CLS contracts;
- `cls:` also owns the local market-management vocabulary for aggregators,
  portfolios, providers, offers, clearing/dispatch extensions, and constraint
  zones.

SAREF is not a primary ontology in this profile. It can be added later as a
crosswalk if an integration requires it. With the capability ON the emitted
profile is byte-identical to the model-first core plus its declared extensions.

## Generated Artifacts

The graph build writes:

```text
instances/default/digital_twin/semantic/nodes.parquet
instances/default/digital_twin/semantic/edges.parquet
instances/default/digital_twin/semantic/graph_manifest.json
instances/default/digital_twin/semantic/validation_report.json
```

The graph uses stable IDs such as:

```text
building:123
bus:45
scenario:S4
contract:S4:building:123:soft_cls
efont:flexibility:S4:building:123:soft_cls
aggregator:S4:soft_cls
portfolio:S4:soft_cls
provider:S4:building:123:soft_cls
offer:S4:building:123:soft_cls
constraint-zone:S4:transformer:64
```

## Node Schema

```text
node_id: string
labels: list/string
semantic_type: string
semantic_uri: string
source_standard: string
source_table: string
source_id: string
name: string|null
scenario_id: string|null
properties: json
```

## Edge Schema

```text
edge_id: string
source_id: string
target_id: string
relationship_type: string
semantic_uri: string
source_standard: string
source_table: string
scenario_id: string|null
properties: json
```

Every node and edge preserves lineage through `source_table` and `source_id`.
This is important: the graph should be auditable back to the current digital
twin Parquet tables.

## Main Relationships

The minimum relationship vocabulary is:

- `(:Building)-[:HAS_LOAD]->(:EnergyConsumer)`;
- `(:EnergyConsumer)-[:CONNECTED_TO]->(:ConnectivityNode)`;
- `(:PowerTransformer)-[:FEEDS]->(:ConnectivityNode)`;
- `(:ACLineSegment)-[:CONNECTS]->(:ConnectivityNode)`;
- `(:Building)-[:HAS_EVSE]->(:EVChargingAsset)`;
- `(:Building)-[:PARTICIPATES_IN]->(:SoftCLSContract)`;
- `(:Building)-[:HAS_FLEXIBILITY_RESOURCE]->(:ThermallyActivatedBuildingSystem)`;
- `(:ThermallyActivatedBuildingSystem)-[:ALLOWS]->(:FlexibleOperation)`;
- `(:FlexibleOperation)-[:ENABLES]->(:EnergyFlexibility)`;
- `(:EnergyFlexibilityKPI)-[:QUANTIFIES]->(:EnergyFlexibility)`;
- `(:SoftCLSContract)-[:DESCRIBES_FLEXIBILITY]->(:EnergyFlexibility)`;
- `(:EVChargingAsset)-[:ENABLES]->(:HardCLSContract)`;
- `(:FlexibilityAggregator)-[:MANAGES_PORTFOLIO]->(:FlexibilityPortfolio)`;
- `(:FlexibilityAggregator)-[:AGGREGATES]->(:FlexibilityProvider)`;
- `(:FlexibilityPortfolio)-[:INCLUDES_PROVIDER]->(:FlexibilityProvider)`;
- `(:FlexibilityProvider)-[:IMPLEMENTS_CONTRACT]->(:SoftCLSContract | :HardCLSContract)`;
- `(:FlexibilityProvider)-[:OFFERS]->(:FlexibilityOffer)`;
- `(:FlexibilityProvider)-[:LOCATED_IN_CONSTRAINT_ZONE]->(:ConstraintZone)`;
- `(:FlexibilityOffer)-[:TARGETS_CONSTRAINT]->(:ConstraintZone)`;
- `(:ConstraintZone)-[:CONSTRAINT_ZONE_FOR]->(:PowerTransformer)`;
- `(:Scenario)-[:INCLUDES_ASSET]->(:Building | :EVChargingAsset | :Contract)`;
- `(:TimeSeriesDataset)-[:OBSERVES]->(:Asset)`;
- `(:SimulationRun)-[:PRODUCED]->(:TimeSeriesDataset)`.

## Market Management Layer

The semantic graph now includes the operational flexibility-management layer
generated from `instances/default/digital_twin/flexibility/provider_registry.parquet`.

Current generated counts:

| Semantic type | Count |
| --- | ---: |
| `cls:FlexibilityAggregator` | 9 |
| `cls:FlexibilityPortfolio` | 9 |
| `cls:FlexibilityProvider` | 8085 |
| `cls:FlexibilityOffer` | 8085 |
| `cls:ConstraintZone` | 810 |

This layer is intentionally local to `cls:` because standards such as OpenADR
and IEEE 2030.5 describe messages and device interoperability, while the
locational market entity model is specific to this digital twin. The graph still
cross-links to standards-backed assets: providers implement CLS contracts,
offers target constraint zones, and each constraint zone resolves to a CIM
`PowerTransformer`.

## EFOnt Crosswalk

EFOnt is integrated as a building-flexibility crosswalk, not as the primary
network or market ontology. CIM still owns grid topology, OpenADR remains the
future demand-response event messaging profile, IEEE 2030.5 remains the future
EV/DER control profile, and `cls:` continues to model Soft/Hard CLS contracts,
clearing, settlement, and network constraints.

For every Soft CLS contract, the graph creates:

- an `efont:ThermallyActivatedBuildingSystem` resource;
- an `efont:FlexibleOperation` representing the dynamic operating envelope or
  setpoint-adjustment operation;
- an `efont:EnergyFlexibility` node representing the delivered building
  flexibility concept;
- an `efont:EnergyFlexibilityKPI` node for `MaximumReducedDemand`.

This gives dashboard, reports, and future FalkorDB consumers a standard language
for building flexibility characteristics without forcing EFOnt to model network
deliverability or CLS market clearing.

## Build And Validate

Generate the graph:

```bash
uv run gridalyn semantic build \
  --profile north_america \
  --base-dir instances/default/digital_twin/base \
  --scenario-dir instances/default/digital_twin/scenarios \
  --flexibility-dir instances/default/digital_twin/flexibility \
  --timeseries-dir instances/default/digital_twin/timeseries \
  --out-dir instances/default/digital_twin/semantic
```

Validate it:

```bash
uv run gridalyn semantic validate \
  --semantic-dir instances/default/digital_twin/semantic
```

The validator checks:

- all edge endpoints exist;
- every building has exactly one load;
- every load connects to a bus;
- scenario EV and CLS counts match the scenario registry;
- semantic types resolve to known namespaces;
- EFOnt crosswalk nodes resolve through the `efont` namespace when present;
- power units are explicit.

## FalkorDB Readiness

The first graph backend is Parquet:

```text
gridalyn/twin/semantic/repository.py
gridalyn/twin/db/federated_graph_adapter.py
```

`SemanticGraphRepository` is the application-facing query API for the Parquet
graph. It answers operational relationship questions such as providers for a
constraint, assets in a scenario, building-to-constraint traces, and
scenario-relevant time-series datasets. The lower-level federated graph adapter
remains a backend migration helper that prepares Cypher batches for FalkorDB or
compatible graph stores. A future FalkorDB writer should import labels from
`semantic_type` and `labels`, not from ad hoc CIM class strings.

Migration rule of thumb:

1. Build the Parquet graph.
2. Pass validation.
3. Dry-run Cypher batches from the adapter (`to_falkor_batches`).
4. Load FalkorDB — **not implemented in-repo**: gridalyn has no FalkorDB
   connection or loader (2026-08-07); loading the exported batches is
   a manual, out-of-repo step.
5. Compare counts and relationship integrity against the Parquet manifest —
   **not implemented**: no in-repo reader exists to perform the comparison.
