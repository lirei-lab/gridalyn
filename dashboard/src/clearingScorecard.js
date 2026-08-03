import { operationalKpiReportPath } from './projectSource.js';

// Resolved per call, not frozen at import (see projectSource.js).

async function loadJsonOrNull(fetchImpl, path) {
  const res = await fetchImpl(path);
  if (!res.ok) return null;
  return res.json();
}

export function normalizeClearingScorecard(report = null, path = operationalKpiReportPath()) {
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

export async function loadClearingScorecard(fetchImpl = fetch, path = operationalKpiReportPath()) {
  const report = await loadJsonOrNull(fetchImpl, path);
  return normalizeClearingScorecard(report, path);
}
