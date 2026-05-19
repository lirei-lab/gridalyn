import test from 'node:test';
import assert from 'node:assert/strict';

import { loadOperationsCatalog, normalizeOperationsCatalog } from './operationsCatalog.js';

test('normalizeOperationsCatalog exposes available operation metrics by scenario', () => {
  const normalized = normalizeOperationsCatalog({
    report_id: 'operations_catalog',
    scenarios: {
      S1: {
        scenario_id: 'S1',
        status: 'not_generated',
        reason: 'No operation artifacts generated for this scenario.',
      },
      S4: {
        scenario_id: 'S4',
        status: 'available',
        operation_id: 'operation:S4:surrogate:test',
        clearing_method: 'surrogate',
        summary: {
          active_constraint_count: 38,
          delivered_mwh: 1.25,
          shortfall_mwh: 0,
          settlement_usd: 90,
          selected_provider_count: 7,
        },
        artifacts: {
          dispatchInstructions: '/projects/flexibility_cls/outputs/operations/dispatch_instructions.parquet',
        },
        reports: {
          operationRun: '/projects/flexibility_cls/outputs/operations/operation_run.json',
          operationalKpis: '/projects/flexibility_cls/outputs/reports/operational_kpi_report.json',
        },
      },
    },
  }, '/ops/catalog.json');

  assert.equal(normalized.source, 'catalog');
  assert.equal(normalized.scenarios.S1.status, 'not_generated');
  assert.equal(normalized.scenarios.S4.status, 'available');
  assert.equal(normalized.scenarios.S4.operationId, 'operation:S4:surrogate:test');
  assert.equal(normalized.scenarios.S4.summary.delivered_mwh, 1.25);
  assert.equal(
    normalized.scenarios.S4.artifacts.dispatchInstructions,
    '/projects/flexibility_cls/outputs/operations/dispatch_instructions.parquet',
  );
  assert.equal(
    normalized.scenarios.S4.reports.operationRun,
    '/projects/flexibility_cls/outputs/operations/operation_run.json',
  );
});

test('loadOperationsCatalog loads the declared catalog path', async () => {
  const requested = [];
  const fetchImpl = async path => {
    requested.push(path);
    return {
      ok: true,
      json: async () => ({
        report_id: 'operations_catalog',
        scenarios: {
          S4: {
            scenario_id: 'S4',
            status: 'available',
            summary: { delivered_mwh: 2.5 },
          },
        },
      }),
    };
  };

  const loaded = await loadOperationsCatalog(fetchImpl, '/custom/operations_catalog.json');

  assert.equal(loaded.scenarios.S4.summary.delivered_mwh, 2.5);
  assert.deepEqual(requested, ['/custom/operations_catalog.json']);
});
