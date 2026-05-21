const DEFAULT_CATALOG_PATH = '/instances/default/digital_twin/flexibility/network_impact_catalog.json';

async function loadJsonOrNull(fetchImpl, path) {
  const res = await fetchImpl(path);
  if (!res.ok) return null;
  return res.json();
}

function caseDispatch(report, caseName) {
  return report?.dispatch?.[caseName] || null;
}

function caseComparison(report, caseName) {
  return report?.comparisons?.[`${caseName}_vs_unmanaged`] || null;
}

function reportScenarioId(...reports) {
  return reports.map(report => report?.scenario_id).find(Boolean) || null;
}

export function normalizeNetworkImpactReports({
  physicsLabels = null,
  physicsSurrogate = null,
  topologyVerification = null,
  physicsVerification = null,
} = {}, paths = {}) {
  const physicsCase = caseDispatch(physicsVerification, 'surrogate_locational');
  const physicsComparison = caseComparison(physicsVerification, 'surrogate_locational');
  const topologyCase = caseDispatch(topologyVerification, 'topology_locational');
  const aggregateCase = caseDispatch(topologyVerification, 'aggregate_cls');
  return {
    scenarioId: reportScenarioId(physicsVerification, topologyVerification, physicsSurrogate, physicsLabels),
    labels: physicsLabels?.summary || null,
    surrogate: physicsSurrogate?.summary || null,
    constraints: physicsVerification?.constraint_ids || topologyVerification?.constraint_ids || [],
    aggregate: aggregateCase,
    topology: topologyCase,
    physics: physicsCase,
    physicsComparison,
    paths,
  };
}

async function loadReportSet(fetchImpl, paths) {
  const [physicsLabels, physicsSurrogate, topologyVerification, physicsVerification] = await Promise.all([
    paths.physicsLabels ? loadJsonOrNull(fetchImpl, paths.physicsLabels) : null,
    paths.physicsSurrogate ? loadJsonOrNull(fetchImpl, paths.physicsSurrogate) : null,
    paths.topologyVerification ? loadJsonOrNull(fetchImpl, paths.topologyVerification) : null,
    paths.physicsVerification ? loadJsonOrNull(fetchImpl, paths.physicsVerification) : null,
  ]);
  return normalizeNetworkImpactReports({
    physicsLabels,
    physicsSurrogate,
    topologyVerification,
    physicsVerification,
  }, paths);
}

async function loadCatalogReports(fetchImpl, catalog, catalogPath) {
  const entries = Object.entries(catalog.scenarios || {});
  const scenarios = {};
  await Promise.all(entries.map(async ([scenarioId, spec]) => {
    const paths = spec.reports || {};
    const normalized = await loadReportSet(fetchImpl, paths);
    scenarios[scenarioId] = {
      ...normalized,
      scenarioId: normalized.scenarioId || spec.scenario_id || scenarioId,
      status: spec.status || 'available',
      reason: spec.reason || null,
    };
  }));
  return {
    source: 'catalog',
    catalogPath,
    scenarios,
  };
}

export async function loadNetworkImpactReports(fetchImpl = fetch, catalogPath = DEFAULT_CATALOG_PATH) {
  const catalog = await loadJsonOrNull(fetchImpl, catalogPath);
  if (catalog?.scenarios) {
    return loadCatalogReports(fetchImpl, catalog, catalogPath);
  }

  return {
    source: 'catalog',
    catalogPath,
    scenarios: {},
  };
}
