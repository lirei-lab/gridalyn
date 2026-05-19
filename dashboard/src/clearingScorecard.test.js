import test from 'node:test';
import assert from 'node:assert/strict';

import { loadClearingScorecard, normalizeClearingScorecard } from './clearingScorecard.js';

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
  assert.deepEqual(requested, ['/projects/flexibility_cls/outputs/reports/operational_kpi_report.json']);
});
