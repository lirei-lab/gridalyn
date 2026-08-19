import test from 'node:test';
import assert from 'node:assert/strict';

import {
  FALLBACK_PROJECT,
  operatingProject,
  operationalKpiReportPath,
  operationsCatalogPath,
  projectOutputsPath,
} from './projectSource.js';

test('operatingProject falls back when no env is configured', () => {
  assert.equal(operatingProject(), FALLBACK_PROJECT);
  assert.equal(operatingProject({}), FALLBACK_PROJECT);
  assert.equal(operatingProject({ VITE_GRIDALYN_PROJECT: '' }), FALLBACK_PROJECT);
});

test('operatingProject honors an explicit VITE_GRIDALYN_PROJECT value', () => {
  assert.equal(
    operatingProject({ VITE_GRIDALYN_PROJECT: 'ieee_33_bus_demo' }),
    'ieee_33_bus_demo',
  );
});

test('projectOutputsPath resolves against operatingProject when no project is given', () => {
  assert.equal(
    projectOutputsPath(['reports', 'x.json']),
    `/projects/${FALLBACK_PROJECT}/outputs/reports/x.json`,
  );
});

test('projectOutputsPath honors an explicit project override', () => {
  assert.equal(
    projectOutputsPath(['reports', 'x.json'], 'synthetic_geojson_feeder'),
    '/projects/synthetic_geojson_feeder/outputs/reports/x.json',
  );
});

test('operationsCatalogPath and operationalKpiReportPath build project-scoped paths', () => {
  assert.equal(
    operationsCatalogPath('minimal_grid_project'),
    '/projects/minimal_grid_project/outputs/operations/operations_catalog.json',
  );
  assert.equal(
    operationalKpiReportPath('minimal_grid_project'),
    '/projects/minimal_grid_project/outputs/reports/operational_kpi_report.json',
  );
});
