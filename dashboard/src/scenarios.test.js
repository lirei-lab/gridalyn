import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildDashboardScenarioCatalog,
  buildScenarioCatalog,
  DEFAULT_SCENARIO_IDS,
  scenarioIdsFromManifest,
} from './scenarios.js';

test('buildDashboardScenarioCatalog uses generic grid metrics and explicit paths', () => {
  const catalog = buildDashboardScenarioCatalog({
    title: 'Grid Twin',
    scenarios: [
      {
        scenario_id: 'WinterPeak',
        label: 'Winter Peak',
        description: 'Cold-weather peak load case',
        paths: {
          nodes: 'instances/default/digital_twin/custom/winter_nodes.parquet',
          lines: 'instances/default/digital_twin/custom/winter_lines.parquet',
          transformers: 'instances/default/digital_twin/custom/winter_transformers.parquet',
          power: 'instances/default/digital_twin/custom/winter_power.parquet',
        },
        metrics: {
          grid_peak_mw: 12.3,
          load_peak_mw: 11.8,
          v_min_pu: 0.945,
          line_max_loading_percent: 82.1,
          trafo_max_loading_percent: 91.2,
        },
        extensions: {
          network_impact: '/instances/default/digital_twin/flexibility/network_impact_catalog.json',
        },
      },
    ],
  });

  assert.equal(catalog.length, 1);
  assert.equal(catalog[0].id, 'WinterPeak');
  assert.equal(catalog[0].label, 'Winter Peak');
  assert.equal(catalog[0].subtitle, 'Cold-weather peak load case');
  assert.equal(catalog[0].gridMetrics.grid_peak_mw, 12.3);
  assert.equal(catalog[0].ext_grid_peak_mw, 12.3);
  assert.equal(catalog[0].paths.nodes, '/instances/default/digital_twin/custom/winter_nodes.parquet');
  assert.equal(catalog[0].extensions.network_impact, '/instances/default/digital_twin/flexibility/network_impact_catalog.json');
});

test('buildScenarioCatalog merges scenario metadata, summaries, asset registry, semantic graph, and explicit paths', () => {
  const scenarioManifest = {
    scenarios: [
      {
        scenario_id: 'WinterPeak',
        ev_penetration_pct: 42,
        n_ev: 1200,
        cls_mode: 'soft-hard',
      },
    ],
  };
  const summaryManifest = {
    scenarios: [
      {
        scenario_id: 'WinterPeak',
        ext_grid_peak_mw: 12.3,
        v_min_pu: 0.945,
        paths: {
          nodes: 'instances/default/digital_twin/custom/winter_nodes.parquet',
          lines: 'instances/default/digital_twin/custom/winter_lines.parquet',
          transformers: 'instances/default/digital_twin/custom/winter_transformers.parquet',
          power: 'instances/default/digital_twin/custom/winter_power.parquet',
        },
      },
    ],
  };
  const assetManifest = {
    scenarios: [
      {
        scenario_id: 'WinterPeak',
        n_soft_participants: 450,
        n_hard_preferred: 760,
        max_hard_kw: 2918.4,
      },
    ],
  };
  const semanticManifest = {
    semantic_profile: 'north_america',
    node_count: 120,
    edge_count: 240,
    validation: { valid: true },
  };

  const catalog = buildScenarioCatalog(scenarioManifest, summaryManifest, assetManifest, semanticManifest);

  assert.equal(catalog.length, 1);
  assert.equal(catalog[0].id, 'WinterPeak');
  assert.equal(catalog[0].subtitle, '42% EV - 1200 EVs - soft-hard');
  assert.equal(catalog[0].ext_grid_peak_mw, 12.3);
  assert.equal(catalog[0].n_soft_participants, 450);
  assert.equal(catalog[0].n_hard_preferred, 760);
  assert.equal(catalog[0].semanticGraph.profile, 'north_america');
  assert.equal(catalog[0].semanticGraph.nodeCount, 120);
  assert.equal(catalog[0].semanticGraph.valid, true);
  assert.equal(catalog[0].paths.nodes, '/instances/default/digital_twin/custom/winter_nodes.parquet');
});

test('buildScenarioCatalog includes summary-only scenarios with conventional metadata', () => {
  const catalog = buildScenarioCatalog(null, {
    scenarios: [{ scenario_id: 'Outage_N1', v_min_pu: 0.91 }],
  });

  assert.equal(catalog.length, 1);
  assert.equal(catalog[0].id, 'Outage_N1');
  assert.equal(catalog[0].label, 'Outage_N1');
  assert.equal(catalog[0].paths.lines, '/instances/default/digital_twin/timeseries/Outage_N1_powerflow_lines.parquet');
});

test('scenarioIdsFromManifest keeps the legacy fallback when no manifest exists', () => {
  assert.deepEqual(scenarioIdsFromManifest(null), DEFAULT_SCENARIO_IDS);
});
