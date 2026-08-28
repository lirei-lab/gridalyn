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

test('loadClearingScorecard fetches exactly the path it is given', async () => {
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

  const declared = '/projects/whatever_study/outputs/reports/operational_kpi_report.json';
  const loaded = await loadClearingScorecard(fetchImpl, declared);

  assert.equal(loaded.scenarioId, 'S4');
  assert.deepEqual(requested, [declared]);
});

test('with no declared path it loads nothing rather than guessing a study', async () => {
  // The default used to resolve to a NAMED study, so a twin that declared no
  // scorecard silently rendered one particular study's numbers as its own.
  // The path now comes from the catalog's
  // `scenarios[].extensions.clearing_scorecard`; absent means absent.
  let called = false;
  const loaded = await loadClearingScorecard(async () => {
    called = true;
    return { ok: true, json: async () => ({ scenario_id: 'X' }) };
  });

  assert.equal(loaded, null);
  assert.equal(called, false, 'no path was declared, so nothing should be fetched');
});
