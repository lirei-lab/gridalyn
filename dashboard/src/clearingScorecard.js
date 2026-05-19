const DEFAULT_SCORECARD_PATH = '/projects/flexibility_cls/outputs/reports/operational_kpi_report.json';

async function loadJsonOrNull(fetchImpl, path) {
  const res = await fetchImpl(path);
  if (!res.ok) return null;
  return res.json();
}

export function normalizeClearingScorecard(report = null, path = DEFAULT_SCORECARD_PATH) {
  if (!report) return null;
  return {
    scenarioId: report.scenario_id || null,
    summary: report.summary || {},
    policies: report.policies || [],
    policyIndex: report.policy_index || {},
    constraintIds: report.constraint_ids || [],
    path,
  };
}

export async function loadClearingScorecard(fetchImpl = fetch, path = DEFAULT_SCORECARD_PATH) {
  const report = await loadJsonOrNull(fetchImpl, path);
  return normalizeClearingScorecard(report, path);
}
