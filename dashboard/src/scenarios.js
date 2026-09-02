import { readProjects } from './projectCatalog.js';
import {
  LEGACY_MANIFEST_PATHS,
  TWIN_CATALOG_PATH,
  TwinDiscoveryError,
  fetchJsonOrNull,
  readGeography,
  readNetworkModel,
  readObservation,
  readSemantic,
  schemaWarning,
  servablePath,
  twinPath,
} from './twinSource.js';

const FILE_KINDS = {
  nodes: 'powerflow_nodes',
  lines: 'powerflow_lines',
  power: 'powerflow_power',
  transformers: 'powerflow_transformers',
};

function scenarioSortKey(id) {
  const match = String(id).match(/^S(\d+)$/);
  return match ? [Number(match[1]), String(id)] : [10000, String(id)];
}

const normalizePath = servablePath;

/**
 * Reconstruct a scenario's paths by naming convention.
 *
 * Only reached by the pre-catalog fallback below, and by a catalog that omits
 * a path. A catalog written by the current SDK always declares all four, so
 * this is a compatibility shim rather than the normal route -- which is why it
 * derives from `twinPath` instead of carrying its own instance literal.
 */
function conventionalPaths(id) {
  return Object.fromEntries(
    Object.entries(FILE_KINDS).map(([kind, suffix]) => [
      kind,
      twinPath(`timeseries/${id}_${suffix}.parquet`),
    ])
  );
}

function normalizePaths(id, paths = {}) {
  const fallback = conventionalPaths(id);
  return Object.fromEntries(
    Object.keys(FILE_KINDS).map(kind => [
      kind,
      normalizePath(paths?.[kind]) || fallback[kind],
    ])
  );
}

function scenarioSubtitle(scenario, summary) {
  const parts = [];
  const pct = scenario?.ev_penetration_pct ?? summary?.ev_penetration_pct;
  const nEv = scenario?.n_ev ?? summary?.n_ev;
  const clsMode = scenario?.cls_mode ?? summary?.cls_mode;
  if (pct !== undefined && pct !== null) parts.push(`${pct}% EV`);
  if (nEv !== undefined && nEv !== null) parts.push(`${nEv} EVs`);
  if (clsMode) parts.push(clsMode);
  return parts.join(' - ');
}

/**
 * The ontology as the PRE-CATALOG manifest states it, for the fallback only.
 *
 * Kept because a twin without a catalog has no other route to its profile, and
 * deliberately not reused on the catalog path: this shape is four scalars, and
 * the four scalars were the problem. `readSemantic` is what the live path
 * reads.
 */
function normalizeSemanticGraph(manifest) {
  if (!manifest) return null;
  return {
    profile: manifest.semantic_profile || null,
    nodeCount: manifest.node_count ?? null,
    edgeCount: manifest.edge_count ?? null,
    valid: manifest.validation?.valid ?? null,
    manifestPath: LEGACY_MANIFEST_PATHS.semanticManifest,
    artifacts: manifest.artifacts || {},
  };
}

/**
 * Narrow the twin's ontology to one scenario.
 *
 * The scenario-scoped population -- the asset registry's class per (scenario,
 * class) pair -- is the only one whose counts differ between scenarios, so
 * carrying the whole list onto every scenario would have each one reporting
 * its siblings' numbers. Classes with no scenario scope are shared unchanged.
 */
export function semanticForScenario(semantic, scenarioId) {
  if (!semantic) return null;
  return {
    ...semantic,
    classes: semantic.classes.filter(
      entry => entry.scenarioId === null || entry.scenarioId === scenarioId
    ),
  };
}

function normalizeMetrics(metrics = {}) {
  const grid_peak_mw = metrics.grid_peak_mw ?? metrics.ext_grid_peak_mw ?? null;
  return {
    ...metrics,
    grid_peak_mw,
    ext_grid_peak_mw: grid_peak_mw,
    load_peak_mw: metrics.load_peak_mw ?? null,
    v_min_pu: metrics.v_min_pu ?? null,
    v_mean_pu: metrics.v_mean_pu ?? null,
    line_max_loading_percent: metrics.line_max_loading_percent ?? null,
    trafo_max_loading_percent: metrics.trafo_max_loading_percent ?? null,
    n_line_overloads: metrics.n_line_overloads ?? null,
    n_trafo_overloads: metrics.n_trafo_overloads ?? null,
  };
}

function normalizeExtensions(extensions = {}) {
  return Object.fromEntries(
    Object.entries(extensions || {}).map(([key, value]) => [key, normalizePath(value)])
  );
}

export function buildDashboardScenarioCatalog(dashboardCatalog) {
  const semantic = readSemantic(dashboardCatalog);
  const observation = readObservation(dashboardCatalog);
  return (dashboardCatalog?.scenarios || [])
    .filter(scenario => scenario?.scenario_id)
    .sort((a, b) => {
      const [ai, as] = scenarioSortKey(a.scenario_id);
      const [bi, bs] = scenarioSortKey(b.scenario_id);
      return ai - bi || as.localeCompare(bs);
    })
    .map(scenario => {
      const id = scenario.scenario_id;
      const metrics = normalizeMetrics(scenario.metrics || {});
      return {
        ...scenario,
        ...metrics,
        id,
        scenario_id: id,
        label: scenario.label || id,
        subtitle: scenario.description || '',
        description: scenario.description || '',
        paths: normalizePaths(id, scenario.paths),
        gridMetrics: metrics,
        topologyCounts: scenario.topology_counts || {},
        extensions: normalizeExtensions(scenario.extensions),
        semanticGraph: semanticForScenario(semantic, id),
        // What this scenario's numbers ARE. Declared per scenario rather than
        // inferred from the instance, so an instance that later carries both
        // kinds does not have to relabel every view at once.
        provenance: scenario.provenance || observation?.provenance || null,
      };
    });
}

export function scenarioIdsFromManifest(manifest) {
  return (manifest?.scenarios || [])
    .map(item => item?.scenario_id)
    .filter(Boolean);
}

export function buildScenarioCatalog(scenarioManifest, summaryManifest, assetManifest = null, semanticManifest = null) {
  const byId = new Map();
  const semanticGraph = normalizeSemanticGraph(semanticManifest);
  for (const scenario of scenarioManifest?.scenarios || []) {
    if (scenario?.scenario_id) {
      byId.set(scenario.scenario_id, { scenario, summary: null, asset: null });
    }
  }
  for (const summary of summaryManifest?.scenarios || []) {
    if (!summary?.scenario_id) continue;
    const existing = byId.get(summary.scenario_id) || { scenario: null, summary: null, asset: null };
    existing.summary = summary;
    byId.set(summary.scenario_id, existing);
  }
  for (const asset of assetManifest?.scenarios || []) {
    if (!asset?.scenario_id) continue;
    const existing = byId.get(asset.scenario_id) || { scenario: null, summary: null, asset: null };
    existing.asset = asset;
    byId.set(asset.scenario_id, existing);
  }

  return Array.from(byId.entries())
    .sort(([a], [b]) => {
      const [ai, as] = scenarioSortKey(a);
      const [bi, bs] = scenarioSortKey(b);
      return ai - bi || as.localeCompare(bs);
    })
    .map(([id, { scenario, summary, asset }]) => {
      const paths = normalizePaths(id, summary?.paths || scenario?.paths);
      const label = scenario?.label || summary?.label || id;
      return {
        ...(asset || {}),
        ...(summary || {}),
        ...(scenario || {}),
        id,
        scenario_id: id,
        label,
        subtitle: scenarioSubtitle(scenario, summary),
        paths,
        semanticGraph,
      };
    });
}

export async function loadScenarioManifest(fetchImpl = fetch) {
  const path = LEGACY_MANIFEST_PATHS.scenarioIndex;
  const res = await fetchImpl(path);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const manifest = await res.json();
  return {
    manifest,
    scenarioIds: scenarioIdsFromManifest(manifest),
  };
}

/**
 * Load everything the dashboard knows about the twin.
 *
 * Returns the whole view -- scenarios, geography, network model, and which
 * source answered -- rather than only the scenario array. The array alone was
 * what kept the map from being catalog-driven: the catalog's geography and
 * model identity were fetched and then discarded one line later.
 *
 * Throws `TwinDiscoveryError` when no source yields a scenario. The previous
 * behaviour returned an empty list, which the UI rendered as a blank panel
 * with the reason confined to the browser console.
 */
export async function loadTwin(fetchImpl = fetch) {
  const catalog = await fetchJsonOrNull(fetchImpl, TWIN_CATALOG_PATH);

  const warnings = [];
  let scenarios = [];
  let source = null;

  if (catalog?.scenarios?.length > 0) {
    const warning = schemaWarning(catalog);
    if (warning) warnings.push(warning);
    scenarios = buildDashboardScenarioCatalog(catalog);
    source = 'catalog';
  } else {
    // Reached only when the catalog answered nothing. Fetching these four
    // alongside the catalog cost every load four needless requests, and -- for
    // the semantic manifest -- made a hardcoded twin path part of the LIVE
    // route rather than of the fallback it belongs to.
    const [scenarioManifest, summaryManifest, assetManifest, semanticManifest] =
      await Promise.all([
        fetchJsonOrNull(fetchImpl, LEGACY_MANIFEST_PATHS.scenarioIndex),
        fetchJsonOrNull(fetchImpl, LEGACY_MANIFEST_PATHS.powerflowSummary),
        fetchJsonOrNull(fetchImpl, LEGACY_MANIFEST_PATHS.assetRegistry),
        fetchJsonOrNull(fetchImpl, LEGACY_MANIFEST_PATHS.semanticManifest),
      ]);
    scenarios = buildScenarioCatalog(
      scenarioManifest,
      summaryManifest,
      assetManifest,
      semanticManifest
    );
    if (scenarios.length > 0) {
      source = 'legacy-manifests';
      warnings.push(
        `no twin catalog at ${TWIN_CATALOG_PATH}; scenarios were reconstructed ` +
          'from the pre-catalog manifests, so geography and model identity are ' +
          'unavailable. Regenerate it with `gridalyn dashboard catalog`.'
      );
    }
  }

  if (scenarios.length === 0) {
    const attempted = [TWIN_CATALOG_PATH, ...Object.values(LEGACY_MANIFEST_PATHS)];
    throw new TwinDiscoveryError(
      'no digital twin found: none of the twin manifests declared a scenario. ' +
        `Looked in ${attempted.join(', ')}. Build a twin with ` +
        '`gridalyn twin build`, then publish its catalog with ' +
        '`gridalyn dashboard catalog`.',
      { attempted }
    );
  }

  return {
    scenarios,
    geography: readGeography(catalog),
    networkModel: readNetworkModel(catalog),
    // Whether this deployment is a shadow, and where its measured state is
    // read from. Null for a pre-1.4 catalog and for the fallback, neither of
    // which can answer -- as distinct from answering "none".
    observation: readObservation(catalog),
    // The twin's ontology, reached through the contract rather than through
    // `LEGACY_MANIFEST_PATHS.semanticManifest`. Null for a pre-1.3 catalog and
    // for the fallback, where no such declaration exists to read.
    semantic: readSemantic(catalog),
    // Studies as SOURCES the twin draws on, described by their declared
    // artifacts. Absent from a pre-catalog twin, hence the empty default.
    projects: readProjects(catalog),
    source,
    warnings,
  };
}

/** Back-compatible shim returning only the scenario array. */
export async function loadScenarioCatalog(fetchImpl = fetch) {
  const twin = await loadTwin(fetchImpl);
  return twin.scenarios;
}
