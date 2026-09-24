# Open The Dashboard

The dashboard is the React application under `dashboard/`
([Interfaces](../components/interfaces.md) describes where it sits). It knows
one URL by heart — the catalog of the `default` twin instance,
`/instances/default/digital_twin/dashboard/catalog.json` — and reads everything
else, scenarios, map layers and study reports, from what that catalog
declares.

## What A Fresh Checkout Already Has

The catalog and the small JSON manifests beside it are committed. The Parquet
files they point at — the base network tables and the per-scenario power-flow
time series — are generated and gitignored. On a fresh checkout the dashboard
therefore opens with the scenario list, the study workspaces and the network
model's counts and extent, but the map has no time series to draw until the
twin is built.

You do not need to regenerate the catalog to open the dashboard: the committed
one is what the dev server serves.

## Run The Development Server

```bash
cd dashboard
npm install
npm run dev
```

Vite serves the application on port 5173 and, through a middleware in
`dashboard/vite.config.js`, serves `instances/default/digital_twin/` and
`projects/` read-only from the repository, so a study's reports appear as soon
as the study has been run. A file that does not exist answers 404, so the
client treats it as absent rather than parsing an HTML fallback page.

`npm test` runs the client's unit tests, including the guards in
`dashboard/src/twinBootstrapGuard.test.js` that keep instance paths, study
names, scenario ids and ontology classes out of the source. `npm run lint`
runs ESLint.

## Fill The Map

The map's layers come from the twin build. Build the `default` instance as
[Build A Twin](build-a-twin.md) describes; the last step of
`gridalyn twin build` regenerates the catalog from what the build wrote, so the
catalog and the Parquet files it names stay in step.

`gridalyn dashboard catalog` regenerates the catalog on its own, from the
artifacts on disk. It writes only from complete inputs: on a checkout without
the generated base tables, power-flow results or semantic graph, it exits
non-zero, lists each missing file with the command that produces it, and
leaves the committed catalog untouched. A layer the instance was never built
with, such as the EV scenarios of a build without `ev-hosting`, is left out
and named on stderr. `--root` and `--instance` select the workspace and the
twin instance, as they do for the `gridalyn twin` commands.

## Check What It Reads

`verify` reads the built instance. Its its generated tables are not committed, so on a fresh clone run `gridalyn twin build` first; otherwise it reports each missing file.

```bash
uv run gridalyn dashboard verify
```

This is read-only. It checks the catalog's `report_id` and `schema_version`,
and that every scenario names its four time-series files and that each one
exists, then prints a JSON verdict and exits non-zero on any error. On a fresh
checkout it lists every scenario's Parquet files as missing — the expected
state until the twin is built.

In the browser, a catalog the client cannot read shows a "Twin not found"
message; the browser console carries the reason.

## Serve It As A Container

```bash
docker compose -f dashboard/docker-compose.yml up -d --build
```

The image builds the application with Node 20 and serves it from nginx on
<http://localhost:8081>. The compose file mounts
`instances/default/digital_twin` and the whole `projects/` tree read-only, so a
rebuilt twin or a re-run study shows up without rebuilding the image. The
documentation site has its own compose file, `docs/docker-compose.yml`.

## Only The Default Instance

The dev server, the compose file and the client's single bootstrap path
(`TWIN_ROOT` in `dashboard/src/twinSource.js`) all name the `default` instance.
A twin built with `--instance <name>` is not visible to the dashboard without
changing those three places.

## What The Catalog Declares

Five blocks carry the contract. Each was added without changing the ones
before it, and the client's supported-version list in
`dashboard/src/twinSource.js` and the verifier's `SUPPORTED_SCHEMA_VERSIONS`
move with every new version:

| Block | Since | What it lets a view do |
|---|---|---|
| `network_model` | 1.0 | Identify the model and report its counts and integrity |
| `network_model.geography` | 1.1 | Open the map on the twin's own extent, in its declared CRS, from the base artifacts it names — and know what kind each geometry is |
| `projects` | 1.2 | Render a study's declared artifacts from the report contract |
| `semantic` | 1.3 | Colour, filter or group by the ontology classes the twin declares |
| `observation` | 1.4 | State whether a rendered number is `simulated` or `measured` |

Two of these answer a question rather than only carrying data, and they answer
it differently on purpose:

- **`semantic` is absent** for a twin with no ontology. "This twin publishes no
  ontology" is a fact about what was built.
- **`observation` is always present.** With nothing measured it carries
  `provenance: "simulated"` and `measured.available: false` with an
  `absent_reason`. "Is anything here measured?" is a question every consumer
  must be able to ask of every instance, and an absent key would make "none"
  and "this catalog is too old to say" the same answer.

`semantic.classes` is the load-bearing part of 1.3. The twin's classes come
from three populations that do not coincide — the base tables' own class
column, the semantic graph's `semantic_type`, and the scenario asset registry —
so every entry names the population it came from, the artifact and columns it
was read off, and whether that artifact's rows carry coordinates. A class the
map can draw and a class it would have to join to reach are different answers,
and the catalog gives both rather than the union.

## Adding An Ontology Class

Nothing in `dashboard/src` names a class, a scenario or an artifact path, and
the guards in `twinBootstrapGuard.test.js` keep it that way. A class added to
the twin therefore reaches the map with no dashboard edit: rebuild the twin
and the class appears in the ontology panel and, when the twin declares its
rows located, as its own map layer with its own colour.

## Feeding Measured Data

To make a deployment a digital shadow by feeding it your own measurements, see
[Feed Measured Data](feed-measured-data.md).
