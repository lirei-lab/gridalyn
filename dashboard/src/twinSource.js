/**
 * Discovery of the digital twin the dashboard is looking at.
 *
 * Everything the dashboard reads is named by the twin's own catalog. The one
 * thing that cannot be discovered is where the catalog itself lives: a client
 * has to know one URL before it can ask anything. TWIN_ROOT is that single
 * bootstrap, and it is deliberately the only instance path in `dashboard/src`.
 * Every other artifact -- scenario timeseries, the base geo tables, the
 * onward extension catalogs -- is resolved from what the catalog declares, so
 * adding a scenario or an artifact to the twin needs no dashboard edit.
 */

const TWIN_ROOT = '/instances/default/digital_twin';

export const TWIN_CATALOG_PATH = `${TWIN_ROOT}/dashboard/catalog.json`;

/**
 * Manifests the pre-catalog fallback reconstructs a scenario list from.
 *
 * Fallback only. `semanticManifest` in particular was read on the LIVE path
 * until the catalog gained a `semantic` block: the dashboard reached the
 * twin's ontology by a hardcoded path -- the exact route the catalog exists to
 * eliminate -- and rendered four scalars off it. `loadTwin` now fetches these
 * only when the catalog yields no scenario, so a twin with a catalog costs one
 * request and asserts no layout.
 */
export const LEGACY_MANIFEST_PATHS = {
  scenarioIndex: `${TWIN_ROOT}/scenarios/index.json`,
  powerflowSummary: `${TWIN_ROOT}/timeseries/powerflow_smoke_summary.json`,
  assetRegistry: `${TWIN_ROOT}/scenarios/asset_registry_summary.json`,
  semanticManifest: `${TWIN_ROOT}/semantic/graph_manifest.json`,
};

/**
 * Catalog schema versions this client understands, oldest first.
 *
 * Must track the SDK's `SUPPORTED_SCHEMA_VERSIONS` in
 * `verify_dashboard_consistency.py`. It did not: 1.2 shipped on the Python
 * side and this list was left at 1.1, so the client warned that the catalog
 * the repo itself ships was unreadable. `twinBootstrapGuard.test.js` now reads
 * the tracked catalog and fails if this list cannot read it.
 */
export const SUPPORTED_SCHEMA_VERSIONS = ['1.0', '1.1', '1.2', '1.3', '1.4'];

/**
 * A twin that could not be discovered, reported with where we looked.
 *
 * Thrown rather than swallowed: the previous behaviour logged to the console
 * and fell back to an empty scenario list, which reaches the user as a blank
 * panel with no statement of what went wrong or which URL was tried.
 */
export class TwinDiscoveryError extends Error {
  constructor(message, { attempted = [], cause = null } = {}) {
    super(message);
    this.name = 'TwinDiscoveryError';
    this.attempted = attempted;
    if (cause) this.cause = cause;
  }
}

export function twinPath(relative) {
  return `${TWIN_ROOT}/${String(relative).replace(/^\/+/, '')}`;
}

/**
 * Normalize a declared path to a servable absolute URL, or null.
 *
 * The catalog declares workspace-relative paths with a leading slash; an
 * absolute http(s) URL is passed through so an externally hosted artifact
 * keeps working.
 */
export function servablePath(path) {
  if (!path) return null;
  if (/^https?:\/\//.test(path)) return path;
  return `/${String(path).replace(/^\/+/, '')}`;
}

/**
 * The twin's geography, as the map layer needs it.
 *
 * Returns null when the catalog declares none -- a 1.0 catalog, or a twin
 * whose base tables carry no coordinates. Callers must treat that as "this
 * twin cannot be mapped", not as an error: an unlocated network is a
 * legitimate model.
 */
export function readGeography(catalog) {
  const geography = catalog?.network_model?.geography;
  if (!geography) return null;
  const extent = geography.extent || null;
  return {
    crs: geography.crs || null,
    // "assumed" means the twin declared no CRS and the SDK fell back to
    // EPSG:4326. Surfaced rather than hidden so a view can say so instead of
    // presenting a guess as a fact.
    crsAssumed: geography.crs_source === 'assumed',
    located: Boolean(geography.located),
    bbox: extent?.bbox || null,
    center: extent?.center || null,
    paths: Object.fromEntries(
      Object.entries(geography.paths || {}).map(([artifact, path]) => [
        artifact,
        servablePath(path),
      ])
    ),
    locatedArtifacts: geography.located_artifacts || {},
    // Lines and transformers carry no coordinates of their own; their
    // geometry is the join of their endpoint buses. Declared by the twin so
    // no consumer rediscovers it by reading a file and finding nothing.
    derivedGeometry: geography.derived_geometry || {},
    // What KIND each geometry is. A coordinate pair says a position exists;
    // it does not say the position is the whole geometry. For `buildings` it
    // is a reduction of a footprint the twin does not retain, and a client
    // that did not know would reasonably draw a polygon layer the twin cannot
    // support.
    geometryKinds: geography.geometry_kinds || {},
  };
}

/**
 * What kind of geometry an artifact has, and why, or null when undeclared.
 *
 * Null for a pre-1.4 catalog: "undeclared" is not "point". A view that needs
 * to know must treat an undeclared kind as unknown rather than assume the
 * shape it would prefer to draw.
 */
export function geometryKind(geography, artifact) {
  const declared = geography?.geometryKinds?.[artifact];
  if (!declared) return null;
  return { kind: declared.kind || null, reason: declared.reason || null };
}

/**
 * The twin's ontology, as the catalog declares it.
 *
 * Returns null for a catalog that declares none -- a pre-1.3 catalog, or a
 * twin with no semantic layer and no scenario asset registry. Null means "this
 * twin publishes no ontology", which is a different statement from an empty
 * class list: a twin whose artifacts genuinely carry no class column publishes
 * an empty list plus `classesAbsentReason` saying why.
 *
 * `classes` is the load-bearing part. Each entry names the class, its row
 * count, the POPULATION it was read from, the artifact and column it was read
 * off, and whether that artifact's rows carry coordinates -- so a consumer can
 * ask for "the classes I can draw" without knowing any class name in advance.
 */
export function readSemantic(catalog) {
  const semantic = catalog?.semantic;
  if (!semantic) return null;
  const graph = semantic.graph || {};
  const validation = graph.validation || {};
  return {
    profile: semantic.profile ?? null,
    nodeCount: graph.node_count ?? null,
    edgeCount: graph.edge_count ?? null,
    valid: validation.valid ?? null,
    errors: validation.errors ?? null,
    warnings: validation.warnings ?? null,
    populations: semantic.populations || [],
    classes: (semantic.classes || []).map(entry => ({
      name: entry.class,
      count: entry.count ?? null,
      population: entry.population ?? null,
      artifact: entry.artifact ?? null,
      column: entry.column ?? null,
      located: Boolean(entry.located),
      // The twin names the columns rather than the client assuming lat/lon.
      coordinates: entry.coordinates ?? null,
      identity: entry.identity ?? null,
      // The column the rows are SCOPED by, declared for the same reason as
      // `coordinates`. Dropping it silently unscoped the query, which drew
      // every scenario's rows at once.
      scenarioColumn: entry.scenario_column ?? null,
      scenarioId: entry.scenario_id ?? null,
      derivedFrom: entry.derived_from || [],
    })),
    // Absent by construction rather than by omission: a twin that declares no
    // class says why, so an empty list is never read as a failed fetch.
    classesAbsentReason: semantic.classes_absent_reason ?? null,
    paths: Object.fromEntries(
      Object.entries(semantic.paths || {}).map(([artifact, path]) => [
        artifact,
        servablePath(path),
      ])
    ),
  };
}

/**
 * Where this instance's numbers come from, and whether it is a shadow.
 *
 * `gridalyn.twin` is a digital MODEL; a deployment becomes a digital SHADOW
 * when its operator feeds it their own measured data. Nothing on screen could
 * express that: the dashboard read scenario timeseries and nothing else, and
 * no rendered value said where it came from.
 *
 * Unlike `readSemantic`, this returns a value for any 1.4 catalog even when
 * there is no measured data -- because "no" is the answer for every instance
 * this repo ships, and it is an answer, not a silence. A pre-1.4 catalog
 * returns null: "too old to say" is genuinely different from "none".
 */
export function readObservation(catalog) {
  const observation = catalog?.observation;
  if (!observation) return null;
  const measured = observation.measured || {};
  return {
    provenance: observation.provenance || null,
    provenanceValues: observation.provenance_values || [],
    measured: {
      available: Boolean(measured.available),
      // Present whenever `available` is false, so a view can say WHY rather
      // than render an empty panel.
      absentReason: measured.absent_reason ?? null,
      directory: servablePath(measured.directory),
      sources: (measured.sources || []).map(servablePath),
      entityJoin: servablePath(measured.entity_join),
      // The contract an operator's export must satisfy, read off the twin
      // rather than restated here.
      columns: measured.columns || [],
      quantities: measured.quantities || [],
      joinColumns: measured.join_columns || [],
    },
  };
}

export function readNetworkModel(catalog) {
  const model = catalog?.network_model;
  if (!model) return null;
  return {
    counts: model.counts || {},
    modelVersionId: model.model_version_id || null,
    modelVersion: model.model_version || {},
    validation: model.validation || null,
  };
}

export async function fetchJsonOrNull(fetchImpl, path) {
  try {
    const res = await fetchImpl(path);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

/**
 * Check a catalog is one this client can read, before anything trusts it.
 *
 * Returns a warning string rather than throwing: an unknown version is worth
 * saying out loud, but the keys this client reads have been stable across
 * every version so far, so refusing to render would be the worse failure.
 */
export function schemaWarning(catalog) {
  const version = catalog?.schema_version;
  if (!version || SUPPORTED_SCHEMA_VERSIONS.includes(version)) return null;
  return (
    `twin catalog declares schema_version ${version}, which this dashboard ` +
    `does not know (supported: ${SUPPORTED_SCHEMA_VERSIONS.join(', ')}). ` +
    'Rendering anyway; some panels may be empty.'
  );
}
