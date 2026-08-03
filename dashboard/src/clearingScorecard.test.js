import test from 'node:test';
import assert from 'node:assert/strict';

import { loadClearingScorecard, normalizeClearingScorecard } from './clearingScorecard.js';
import { FALLBACK_PROJECT, operatingProject, operationalKpiReportPath } from './projectSource.js';

test('normalizeClearingScorecard exposes scenario policies and summary', () => {
  const normalized = normalizeClearingScorecard({
    scenario_id: 'S4',
    summary: {
      best_delivery_policy_id: 'aggregate_cls',
    },
    policies: [
      {
        policy_id: 'aggregate_cls',
        total_delivered_mwh: 6.5,
      },
    ],
    policy_index: {
      aggregate_cls: { policy_id: 'aggregate_cls' },
    },
    constraint_ids: ['transformer:64'],
  });

  assert.equal(normalized.scenarioId, 'S4');
  assert.equal(normalized.summary.best_delivery_policy_id, 'aggregate_cls');
  assert.equal(normalized.policies[0].total_delivered_mwh, 6.5);
  assert.deepEqual(normalized.constraintIds, ['transformer:64']);
});

test('loadClearingScorecard loads the canonical report path', async () => {
  const requested = [];
  const fetchImpl = async path => {
    requested.push(path);
    return {
      ok: true,
      json: async () => ({
        scenario_id: 'S4',
        policies: [],
      }),
    };
  };

  const loaded = await loadClearingScorecard(fetchImpl);

  assert.equal(loaded.scenarioId, 'S4');
  // Asserts the RESOLUTION, not a literal project. This test previously
  // pinned the path to one study by name, which is what kept the dashboard
  // wired to it: changing the operating project meant changing this file.
  assert.deepEqual(requested, [operationalKpiReportPath()]);
  assert.ok(requested[0].startsWith(`/projects/${FALLBACK_PROJECT}/`));
});

test('the operating project is configurable, not baked in', () => {
  assert.equal(
    operationalKpiReportPath('some_other_study'),
    '/projects/some_other_study/outputs/reports/operational_kpi_report.json',
  );
  assert.equal(operatingProject({ VITE_GRIDALYN_PROJECT: 'from_env' }), 'from_env');
  assert.equal(operatingProject({}), FALLBACK_PROJECT);
});
