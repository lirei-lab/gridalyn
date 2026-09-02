import assert from 'node:assert/strict';
import test from 'node:test';

import {
  declaredMetrics,
  describeScenarios,
  deriveWorkspaces,
  governedMetrics,
  partitionSummary,
  formatSummaryValue,
  governedReports,
  loadProjectReports,
  readProjects,
  summaryRows,
  tables,
} from './projectCatalog.js';

const CATALOG = {
  schema_version: '1.2',
  projects: [
    {
      project_id: 'minimal_grid_project',
      label: 'Minimal Grid Project',
      description: 'The smallest complete study.',
      base_path: '/projects/minimal_grid_project',
      artifacts: [
        {
          path: '/projects/minimal_grid_project/outputs/reports/minimal_grid_report.json',
          relative: 'outputs/reports/minimal_grid_report.json',
          kind: 'governed_report',
          exists: true,
          report_id: 'minimal_grid_report',
          source_domain: 'minimal_grid_project',
        },
        {
          path: '/projects/minimal_grid_project/outputs/data/buses.csv',
          relative: 'outputs/data/buses.csv',
          kind: 'table',
          exists: true,
        },
      ],
    },
    {
      project_id: 'heavy_study',
      label: 'Heavy Study',
      base_path: '/projects/heavy_study',
      artifacts: [
        {
          path: '/projects/heavy_study/outputs/reports/x_report.json',
          relative: 'outputs/reports/x_report.json',
          kind: 'governed_report',
          exists: false,
        },
      ],
    },
  ],
};

test('the workspace list is derived from the catalog, with the twin first', () => {
  const workspaces = deriveWorkspaces(readProjects(CATALOG));
  assert.equal(workspaces[0].id, 'digital_twin');
  assert.deepEqual(
    workspaces.map(workspace => workspace.id),
    ['digital_twin', 'minimal_grid_project', 'heavy_study']
  );
});

test('a study added to the catalog appears with no dashboard edit', () => {
  const grown = { projects: [...CATALOG.projects, { project_id: 'brand_new', artifacts: [] }] };
  const ids = deriveWorkspaces(readProjects(grown)).map(workspace => workspace.id);
  assert.ok(ids.includes('brand_new'));
});

test('a study whose outputs are absent is listed but flagged, not omitted', () => {
  // The two heavy studies gitignore their outputs; dropping them from the list
  // would make an unrun study indistinguishable from a nonexistent one.
  const workspaces = deriveWorkspaces(readProjects(CATALOG));
  const heavy = workspaces.find(workspace => workspace.id === 'heavy_study');
  assert.equal(heavy.available, false);
  const minimal = workspaces.find(workspace => workspace.id === 'minimal_grid_project');
  assert.equal(minimal.available, true);
});

test('governed reports and tables are separated by declared kind', () => {
  const workspace = deriveWorkspaces(readProjects(CATALOG))[1];
  assert.equal(governedReports(workspace).length, 1);
  assert.equal(tables(workspace).length, 1);
  assert.equal(tables(workspace)[0].relative, 'outputs/data/buses.csv');
});

test('a pre-1.2 catalog yields no projects rather than throwing', () => {
  assert.deepEqual(readProjects({ schema_version: '1.1' }), []);
  assert.deepEqual(readProjects(null), []);
});

test('summary rows come from the report contract, not a per-study mapping', () => {
  const rows = summaryRows({ min_voltage_pu: 0.9512345, converged: true, network: 'ieee33' });
  assert.deepEqual(
    rows.map(row => row.key),
    ['converged', 'min_voltage_pu', 'network']
  );
  assert.equal(rows.find(row => row.key === 'converged').value, 'yes');
  assert.equal(rows.find(row => row.key === 'min_voltage_pu').value, '0.9512');
  assert.equal(rows.find(row => row.key === 'min_voltage_pu').label, 'min voltage pu');
});

test('summary values are formatted by type, so any study renders', () => {
  assert.equal(formatSummaryValue(null), '—');
  assert.equal(formatSummaryValue(42), '42');
  assert.equal(formatSummaryValue(1.23456), '1.2346');
  assert.equal(formatSummaryValue(false), 'no');
  assert.equal(formatSummaryValue('ieee33'), 'ieee33');
  // Nested values are shown, not silently dropped.
  assert.equal(formatSummaryValue({ a: 1 }), '{"a":1}');
});

test('a report that fails to load is reported in place, not dropped', async () => {
  const workspace = deriveWorkspaces(readProjects(CATALOG))[1];
  const loaded = await loadProjectReports(workspace, async () => ({ ok: false, status: 500 }));
  assert.equal(loaded.length, 1);
  assert.equal(loaded[0].report, null);
  assert.equal(loaded[0].error, 'HTTP 500');
});

test('a report that loads carries its payload through', async () => {
  const workspace = deriveWorkspaces(readProjects(CATALOG))[1];
  const loaded = await loadProjectReports(workspace, async () => ({
    ok: true,
    json: async () => ({ report_id: 'minimal_grid_report', summary: { converged: true } }),
  }));
  assert.equal(loaded[0].error, null);
  assert.equal(loaded[0].report.summary.converged, true);
});

test('a thrown fetch is captured rather than rejecting the whole load', async () => {
  const workspace = deriveWorkspaces(readProjects(CATALOG))[1];
  const loaded = await loadProjectReports(workspace, async () => {
    throw new Error('offline');
  });
  assert.equal(loaded[0].error, 'offline');
});

test('a study carries the scenarios its catalog entry declares', () => {
  const [twin, study] = deriveWorkspaces([
    {
      project_id: 'demo',
      artifacts: [{ path: '/x.json', exists: true, kind: 'governed_report' }],
      scenarios: [
        {
          scenario_id: 'baseline',
          label: 'Original feeder.',
          paths: { results: '/p/results.csv', profiles: '/p/profiles.csv' },
          partitioning: {
            results: { kind: 'results', partitioning: 'column', id_column: 'scenario_id' },
            profiles: { kind: 'profiles', partitioning: 'column', id_column: 'scenario_id' },
          },
        },
      ],
    },
  ]);
  assert.equal(twin.id, 'digital_twin');
  assert.equal(study.scenarios.length, 1);
});

test('a study that declares no indexer carries no scenarios', () => {
  // Most studies. The section must not render, rather than render empty.
  const [, study] = deriveWorkspaces([{ project_id: 'demo', artifacts: [] }]);
  assert.deepEqual(study.scenarios, []);
  assert.deepEqual(describeScenarios(study), []);
});

test('describeScenarios reports the kinds declared, never a set it expects', () => {
  const workspace = {
    scenarios: [
      {
        scenario_id: 'baseline',
        paths: { anything_at_all: '/p/x.csv' },
        partitioning: {
          anything_at_all: {
            kind: 'anything_at_all',
            partitioning: 'column',
            id_column: 'run_id',
          },
        },
      },
    ],
  };
  const [scenario] = describeScenarios(workspace);
  assert.equal(scenario.id, 'baseline');
  // Falls back to the id when the index declared no label column.
  assert.equal(scenario.label, 'baseline');
  assert.deepEqual(scenario.kinds, [
    {
      kind: 'anything_at_all',
      path: '/p/x.csv',
      partitioning: 'column',
      idColumn: 'run_id',
    },
  ]);
});

test('a kind with no declared partitioning reports null, not a guess', () => {
  // Reading a column-partitioned file as if it were file-partitioned renders
  // another scenario's rows as this one's, so an absent declaration must stay
  // absent rather than defaulting.
  const [scenario] = describeScenarios({
    scenarios: [{ scenario_id: 's', paths: { k: '/p/k.csv' } }],
  });
  assert.equal(scenario.kinds[0].partitioning, null);
  assert.equal(scenario.kinds[0].idColumn, null);
});

test('partitionSummary promotes only what the study declared or pins', () => {
  const rows = [
    { key: 'objective_value', label: 'objective value', value: '0.3148' },
    { key: 'bus_count', label: 'bus count', value: '16' },
    { key: 'solver_status', label: 'solver status', value: 'optimal' },
  ];
  const { headline, supporting } = partitionSummary(rows, {
    declared: ['objective_value'],
    governed: ['solver_status'],
  });
  assert.deepEqual(headline.map(r => r.key), ['objective_value', 'solver_status']);
  assert.deepEqual(supporting.map(r => r.key), ['bus_count']);
  assert.equal(headline[0].declared, true);
  assert.equal(headline[1].governed, true);
});

test('a value that is both declared and governed carries both marks', () => {
  // The strongest claim the contract can make about a result: the study set
  // out to measure it AND a re-run is checked against it. Merging the two
  // signals would lose that.
  const [row] = partitionSummary([{ key: 'episode_count', label: 'x', value: '90' }], {
    declared: ['episode_count'],
    governed: ['episode_count'],
  }).headline;
  assert.equal(row.declared, true);
  assert.equal(row.governed, true);
});

test('a study that declares nothing promotes nothing', () => {
  // Two shipped studies declare no metrics. Promoting by a guess would be
  // inventing importance the study never claimed.
  const rows = [{ key: 'a', label: 'a', value: '1' }];
  const { headline, supporting } = partitionSummary(rows);
  assert.deepEqual(headline, []);
  assert.equal(supporting.length, 1);
});

test('governedMetrics is scoped to the report that pins it', () => {
  // Two reports of one study can carry the same key and only one be pinned.
  const workspace = {
    governed_metrics: [
      { key: 'min_voltage_pu', source: 'outputs/reports/a.json' },
      { key: 'other', source: 'outputs/reports/b.json' },
    ],
  };
  assert.deepEqual(governedMetrics(workspace, 'outputs/reports/a.json'), [
    'min_voltage_pu',
  ]);
  assert.deepEqual(governedMetrics(workspace, 'outputs/reports/b.json'), ['other']);
});

test('declaredMetrics unions every experiment the study declares', () => {
  assert.deepEqual(
    declaredMetrics({
      experiments: [{ metrics: ['a', 'b'] }, { metrics: ['b', 'c'] }],
    }),
    ['a', 'b', 'c']
  );
  assert.deepEqual(declaredMetrics({}), []);
});
