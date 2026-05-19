const DEFAULT_OPERATIONS_CATALOG_PATH = '/projects/flexibility_cls/outputs/operations/operations_catalog.json';

async function loadJsonOrNull(fetchImpl, path) {
  const res = await fetchImpl(path);
  if (!res.ok) return null;
  return res.json();
}

function normalizeScenarioOperation(scenarioId, spec = {}) {
  return {
    scenarioId: spec.scenario_id || scenarioId,
    status: spec.status || 'available',
    reason: spec.reason || null,
    operationId: spec.operation_id || null,
    clearingMethod: spec.clearing_method || null,
    ontologyProfile: spec.ontology_profile || null,
    governance: spec.governance || {},
    summary: spec.summary || {},
    artifacts: spec.artifacts || {},
    reports: spec.reports || {},
  };
}

export function normalizeOperationsCatalog(catalog = null, path = DEFAULT_OPERATIONS_CATALOG_PATH) {
  if (!catalog?.scenarios) return null;
  const scenarios = {};
  for (const [scenarioId, spec] of Object.entries(catalog.scenarios || {})) {
    scenarios[scenarioId] = normalizeScenarioOperation(scenarioId, spec);
  }
  return {
    source: 'catalog',
    catalogPath: path,
    reportId: catalog.report_id || null,
    projectId: catalog.project_id || null,
    title: catalog.title || 'Flexibility Operations',
    availableScenarios: catalog.available_scenarios || [],
    expectedScenarios: catalog.expected_scenarios || Object.keys(scenarios),
    scenarios,
  };
}

export async function loadOperationsCatalog(fetchImpl = fetch, path = DEFAULT_OPERATIONS_CATALOG_PATH) {
  const catalog = await loadJsonOrNull(fetchImpl, path);
  return normalizeOperationsCatalog(catalog, path);
}
