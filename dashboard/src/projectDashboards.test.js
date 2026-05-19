import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildIeeeVoltageChartRows,
  loadIeee33Dashboard,
  normalizeScenarioRows,
  parseCsv,
} from './projectDashboards.js';

test('parseCsv returns object rows', () => {
  assert.deepEqual(parseCsv('a,b\n1,2\n3,4\n'), [
    { a: '1', b: '2' },
    { a: '3', b: '4' },
  ]);
});

test('normalizeScenarioRows exposes grid metrics', () => {
  const [row] = normalizeScenarioRows([
    {
      scenario_id: 'pv_midday',
      description: 'PV case',
      total_load_mw: '3.7',
      total_generation_mw: '1.0',
      net_demand_mw: '2.7',
      line_loss_mw: '0.1',
      min_voltage_pu: '0.94',
      max_voltage_pu: '1.0',
      max_line_loading_percent: '12.5',
      voltage_violation_count: '3',
      converged: 'True',
    },
  ]);

  assert.equal(row.scenarioId, 'pv_midday');
  assert.equal(row.totalLoadMw, 3.7);
  assert.equal(row.totalGenerationMw, 1.0);
  assert.equal(row.converged, true);
});

test('buildIeeeVoltageChartRows pivots voltage rows by scenario', () => {
  const rows = buildIeeeVoltageChartRows([
    { busId: 1, scenarioId: 'baseline', vmPu: 1.0 },
    { busId: 1, scenarioId: 'ev_evening_peak', vmPu: 0.98 },
    { busId: 2, scenarioId: 'baseline', vmPu: 0.99 },
  ]);

  assert.deepEqual(rows, [
    { busId: 1, baseline: 1.0, ev_evening_peak: 0.98 },
    { busId: 2, baseline: 0.99 },
  ]);
});

test('loadIeee33Dashboard loads reports and CSV artifacts', async () => {
  const responses = {
    '/demo/reports/ieee33_powerflow_report.json': {
      ok: true,
      json: async () => ({ summary: { bus_count: 33 } }),
    },
    '/demo/reports/ieee33_scenario_comparison_report.json': {
      ok: true,
      json: async () => ({ summary: { scenario_count: 5 } }),
    },
    '/demo/data/scenario_results.csv': {
      ok: true,
      text: async () => 'scenario_id,min_voltage_pu,converged\nbaseline,0.91,True\n',
    },
    '/demo/data/scenario_voltage_profiles.csv': {
      ok: true,
      text: async () => 'scenario_id,bus_id,vm_pu\nbaseline,0,1.0\n',
    },
  };

  const dashboard = await loadIeee33Dashboard(async path => responses[path], '/demo');

  assert.equal(dashboard.powerflow.bus_count, 33);
  assert.equal(dashboard.scenarioSummary.scenario_count, 5);
  assert.equal(dashboard.scenarios[0].scenarioId, 'baseline');
  assert.equal(dashboard.voltageChartRows[0].baseline, 1.0);
});
