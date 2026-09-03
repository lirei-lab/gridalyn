# Open The Dashboard

The dashboard is a general grid and operations viewer. It should load scenarios,
reports, and network-impact metadata from generated catalog files rather than
from hard-coded study assumptions.

## Generate Or Refresh The Catalog

```bash
uv run gridalyn dashboard catalog
```

## Run The Dashboard

For local development, inspect the dashboard package instructions:

```bash
cd dashboard
npm install
npm run dev
```

For container deployment, use the compose file that applies to your environment.
The documentation site itself is served separately from `docs/docker-compose.yml`.

## What To Check

After opening the dashboard:

- scenario selection should be programmatic;
- grid metrics should update with the selected scenario;
- EV-specific text should not dominate the general platform view;
- network-impact and semantic summary cards should come from catalog/report
  metadata;
- missing optional reports should degrade gracefully.

## What The Catalog Declares

Everything the dashboard reads is named by `catalog.json`; the only path the
client knows by heart is the catalog's own URL. Four blocks carry the contract,
each added additively and each with the client's supported-version list moved
with it:

| Block | Since | What it lets a view do |
|---|---|---|
| `network_model` | 1.0 | Identify the model and report its counts and integrity |
| `network_model.geography` | 1.1 | Open the map on the twin's own extent, in its declared CRS, from the base artifacts it names — and know what KIND each geometry is |
| `projects` | 1.2 | Render a study's declared artifacts from the report contract |
| `semantic` | 1.3 | Colour, filter or group by the ontology CLASSES the twin declares |
| `observation` | 1.4 | State whether a rendered number is `simulated` or `measured` |

Two of these answer a question rather than only carrying data, and they answer
it differently on purpose:

- **`semantic` is absent** for a twin with no ontology. "This twin publishes no
  ontology" is a fact about what was built.
- **`observation` is always present**, saying `available: false` with a reason
  when there is nothing measured. "Is anything here measured?" is a question
  every consumer must be able to ask of every instance, and an absent key would
  make "none" and "this catalog is too old to say" the same observation.

`semantic.classes` is the load-bearing part of 1.3. The twin's classes come
from three populations that do **not** coincide — the base tables' own class
column, the semantic graph's `semantic_type`, and the scenario asset registry —
so every entry names the population it came from, the artifact and columns it
was read off, and whether that artifact's rows carry coordinates. A class the
map can draw and a class it would have to join to reach are different answers,
and the catalog gives both rather than the union.

## Adding An Ontology Class

Nothing in `dashboard/src` names a class, a scenario or an artifact path, and
guards in `twinBootstrapGuard.test.js` keep it that way. A class added to the
twin therefore reaches the map with no dashboard edit: regenerate the catalog
and it appears in the ontology panel and, when the twin declares its rows
located, as its own map layer with its own colour.

## Feeding Measured Data

The SDK ships the ingest *path*, not measured data. To make a deployment a
digital **shadow** rather than a model, put tidy measurement exports and the
declared entity join in the directory the catalog names under
`observation.measured.directory`:

```text
instances/<name>/digital_twin/observations/
  ami_export.csv          # timestamp, entity_id, quantity, value
  entity_join.csv         # entity_id, bus_id
```

The exact columns and the supported quantities are published in
`observation.measured` rather than restated here, so an operator reads the
contract off their own twin. Both halves are required: which entity sits on
which bus is a fact only the operator knows, and
`gridalyn.twin.observation.ingest` refuses to infer it.

See [Dashboard](../components/interfaces.md) for the data contracts.
