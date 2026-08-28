

async function loadJsonOrNull(fetchImpl, path) {
  const res = await fetchImpl(path);
  if (!res.ok) return null;
  return res.json();
}

export function normalizeClearingScorecard(report = null, path = null) {
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

/**
 * Load the clearing scorecard a scenario declares.
 *
 * As with the operations catalog, there is no default path: it comes from
 * `scenarios[].extensions.clearing_scorecard`, and an absent declaration means
 * this twin has no scorecard, not that it has some other study's.
 */
export async function loadClearingScorecard(fetchImpl = fetch, path = null) {
  if (!path) return null;
  const report = await loadJsonOrNull(fetchImpl, path);
  return normalizeClearingScorecard(report, path);
}
