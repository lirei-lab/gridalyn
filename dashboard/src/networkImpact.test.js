import test from 'node:test';
import assert from 'node:assert/strict';

import { loadNetworkImpactReports, normalizeNetworkImpactReports } from './networkImpact.js';

test('normalizeNetworkImpactReports extracts label, surrogate, and verification metrics', () => {
  const normalized = normalizeNetworkImpactReports({
    physicsLabels: {
      summary: {
        n_samples: 3888,
        provider_count: 72,
      },
    },
    physicsSurrogate: {
      summary: {
        n_supervised_pairs: 69,
        n_positive_predictions: 114,
      },
    },
    topologyVerification: {
      constraint_ids: ['transformer:64'],
      dispatch: {
        aggregate_cls: { total_delivered_mwh: 6.57 },
        topology_locational: { total_delivered_mwh: 1.08 },
      },
    },
    physicsVerification: {
      scenario_id: 'S4',
      constraint_ids: ['transformer:64', 'transformer:99'],
      dispatch: {
        surrogate_locational: {
          total_delivered_mwh: 1.08,
          total_shortfall_mwh: 5.5,
        },
      },
      comparisons: {
        surrogate_locational_vs_unmanaged: {
          trafo_max_loading_reduction_pctpt: 1.66,
          trafo_overload_delta: -3,
        },
      },
    },
  });

  assert.equal(normalized.labels.n_samples, 3888);
  assert.equal(normalized.scenarioId, 'S4');
  assert.equal(normalized.surrogate.n_supervised_pairs, 69);
  assert.deepEqual(normalized.constraints, ['transformer:64', 'transformer:99']);
  assert.equal(normalized.aggregate.total_delivered_mwh, 6.57);
  assert.equal(normalized.topology.total_delivered_mwh, 1.08);
  assert.equal(normalized.physics.total_shortfall_mwh, 5.5);
  assert.equal(normalized.physicsComparison.trafo_overload_delta, -3);
});

test('normalizeNetworkImpactReports falls back to report scenario id from labels', () => {
  const normalized = normalizeNetworkImpactReports({
    physicsLabels: {
      scenario_id: 'S4',
      summary: { n_samples: 3888 },
    },
  });

  assert.equal(normalized.scenarioId, 'S4');
});

test('normalizeNetworkImpactReports tolerates missing reports', () => {
  const normalized = normalizeNetworkImpactReports();

  assert.equal(normalized.labels, null);
  assert.equal(normalized.surrogate, null);
  assert.equal(normalized.aggregate, null);
  assert.deepEqual(normalized.constraints, []);
});

test('loadNetworkImpactReports loads scenario-specific reports from catalog', async () => {
  const responses = new Map([
    [
      '/digital_twin/flexibility/network_impact_catalog.json',
      {
        scenarios: {
          S1: {
            scenario_id: 'S1',
            status: 'not_generated',
            reports: {},
          },
          S4: {
            scenario_id: 'S4',
            status: 'available',
            reports: {
              physicsLabels: '/custom/S4_labels.json',
              physicsVerification: '/custom/S4_verification.json',
            },
          },
        },
      },
    ],
    [
      '/custom/S4_labels.json',
      {
        scenario_id: 'S4',
        summary: {
          n_samples: 12,
          provider_count: 4,
        },
      },
    ],
    [
      '/custom/S4_verification.json',
      {
        scenario_id: 'S4',
        constraint_ids: ['transformer:64'],
        dispatch: {
          surrogate_locational: {
            total_delivered_mwh: 1.2,
          },
        },
      },
    ],
  ]);
  const requested = [];
  const fetchImpl = async path => {
    requested.push(path);
    return {
      ok: responses.has(path),
      json: async () => responses.get(path),
    };
  };

  const loaded = await loadNetworkImpactReports(fetchImpl);

  assert.equal(loaded.scenarios.S1.status, 'not_generated');
  assert.equal(loaded.scenarios.S4.status, 'available');
  assert.equal(loaded.scenarios.S4.labels.n_samples, 12);
  assert.equal(loaded.scenarios.S4.physics.total_delivered_mwh, 1.2);
  assert.deepEqual(requested, [
    '/digital_twin/flexibility/network_impact_catalog.json',
    '/custom/S4_labels.json',
    '/custom/S4_verification.json',
  ]);
});
