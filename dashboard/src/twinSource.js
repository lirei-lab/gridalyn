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

/** Manifests the pre-catalog fallback reconstructs a scenario list from. */
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
export const SUPPORTED_SCHEMA_VERSIONS = ['1.0', '1.1', '1.2'];

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
