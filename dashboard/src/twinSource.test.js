import assert from 'node:assert/strict';
import test from 'node:test';

import {
  LEGACY_MANIFEST_PATHS,
  TWIN_CATALOG_PATH,
  TwinDiscoveryError,
  readGeography,
  readNetworkModel,
  schemaWarning,
  servablePath,
  twinPath,
} from './twinSource.js';
import { loadTwin } from './scenarios.js';

function jsonResponse(payload) {
  return { ok: true, json: async () => payload };
}

const MISSING = { ok: false, status: 404, json: async () => null };

function fetcher(byPath) {
  return async path => byPath[path] ?? MISSING;
}

const SCENARIO_PATHS = {
  nodes: '/instances/default/digital_twin/timeseries/S0_powerflow_nodes.parquet',
  lines: '/instances/default/digital_twin/timeseries/S0_powerflow_lines.parquet',
  power: '/instances/default/digital_twin/timeseries/S0_powerflow_power.parquet',
  transformers:
    '/instances/default/digital_twin/timeseries/S0_powerflow_transformers.parquet',
};

const GEOGRAPHY = {
  crs: 'EPSG:4326',
  crs_source: 'assumed',
  located: true,
  extent: {
    bbox: [-72.62, 46.33, -72.58, 46.35],
    center: { lon: -72.6, lat: 46.34 },
  },
  paths: {
    grid_buses: '/instances/default/digital_twin/base/grid_buses.parquet',
    grid_lines: '/instances/default/digital_twin/base/grid_lines.parquet',
  },
  located_artifacts: { grid_buses: { latitude: 'lat', longitude: 'lon' } },
  derived_geometry: { grid_lines: ['from_bus', 'to_bus'] },
};

function catalog(overrides = {}) {
  return {
    report_id: 'digital_twin_dashboard_catalog',
    schema_version: '1.1',
    network_model: {
      counts: { buses: 3562 },
      model_version_id: 'model:sha256:abc',
      validation: { valid: true },
      geography: GEOGRAPHY,
    },
    scenarios: [{ scenario_id: 'S0', label: 'Base', paths: SCENARIO_PATHS }],
    ...overrides,
  };
}

test('the twin root is the only bootstrap, and every path derives from it', () => {
  assert.equal(TWIN_CATALOG_PATH, '/instances/default/digital_twin/dashboard/catalog.json');
  assert.equal(twinPath('base/grid_buses.parquet'), '/instances/default/digital_twin/base/grid_buses.parquet');
  assert.equal(twinPath('/base/x.parquet'), '/instances/default/digital_twin/base/x.parquet');
});

test('servablePath passes absolute URLs through and normalizes the rest', () => {
  assert.equal(servablePath('https://cdn.example/x.parquet'), 'https://cdn.example/x.parquet');
  assert.equal(servablePath('instances/a/b.parquet'), '/instances/a/b.parquet');
  assert.equal(servablePath(null), null);
});

test('readGeography surfaces the extent, the centre and the derived geometry', () => {
  const geography = readGeography(catalog());
  assert.equal(geography.located, true);
  assert.deepEqual(geography.bbox, [-72.62, 46.33, -72.58, 46.35]);
  assert.deepEqual(geography.center, { lon: -72.6, lat: 46.34 });
  assert.deepEqual(geography.derivedGeometry.grid_lines, ['from_bus', 'to_bus']);
  assert.equal(geography.paths.grid_buses, '/instances/default/digital_twin/base/grid_buses.parquet');
});

test('an assumed CRS is flagged so a view can say so rather than imply a fact', () => {
  assert.equal(readGeography(catalog()).crsAssumed, true);
  const declared = catalog();
  declared.network_model.geography = { ...GEOGRAPHY, crs_source: 'declared' };
  assert.equal(readGeography(declared).crsAssumed, false);
});

test('a catalog without geography reads as null, not as an error', () => {
  assert.equal(readGeography({ schema_version: '1.0', network_model: {} }), null);
  assert.equal(readGeography(null), null);
});

test('readNetworkModel carries counts and model identity', () => {
  const model = readNetworkModel(catalog());
  assert.equal(model.counts.buses, 3562);
  assert.equal(model.modelVersionId, 'model:sha256:abc');
});

test('schemaWarning fires only on a version this client does not know', () => {
  assert.equal(schemaWarning(catalog()), null);
  assert.equal(schemaWarning(catalog({ schema_version: '1.0' })), null);
  assert.match(schemaWarning(catalog({ schema_version: '9.9' })), /9\.9/);
});

test('loadTwin returns the whole view, not only the scenario array', async () => {
  const twin = await loadTwin(fetcher({ [TWIN_CATALOG_PATH]: jsonResponse(catalog()) }));
  assert.equal(twin.source, 'catalog');
  assert.equal(twin.scenarios.length, 1);
  assert.equal(twin.scenarios[0].id, 'S0');
  assert.equal(twin.geography.located, true);
  assert.equal(twin.networkModel.counts.buses, 3562);
  assert.deepEqual(twin.warnings, []);
});

test('a scenario added to the twin appears with no dashboard edit', async () => {
  const grown = catalog();
  grown.scenarios.push({ scenario_id: 'S9', label: 'New', paths: SCENARIO_PATHS });
  const twin = await loadTwin(fetcher({ [TWIN_CATALOG_PATH]: jsonResponse(grown) }));
  assert.deepEqual(
    twin.scenarios.map(scenario => scenario.id),
    ['S0', 'S9']
  );
});

test('a missing catalog falls back to the legacy manifests and says so', async () => {
  const twin = await loadTwin(
    fetcher({
      [LEGACY_MANIFEST_PATHS.scenarioIndex]: jsonResponse({
        scenarios: [{ scenario_id: 'S0', label: 'Base' }],
      }),
    })
  );
  assert.equal(twin.source, 'legacy-manifests');
  assert.equal(twin.geography, null);
  assert.match(twin.warnings[0], /no twin catalog/);
  assert.match(twin.warnings[0], /gridalyn dashboard catalog/);
});

test('no twin at all fails with a located message, not a blank panel', async () => {
  await assert.rejects(
    () => loadTwin(fetcher({})),
    error => {
      assert.ok(error instanceof TwinDiscoveryError);
      // The message must name every URL tried and the command that fixes it;
      // the previous behaviour returned [] and left the reason in the console.
      assert.match(error.message, /no digital twin found/);
      assert.match(error.message, /gridalyn twin build/);
      assert.ok(error.attempted.includes(TWIN_CATALOG_PATH));
      assert.ok(error.attempted.includes(LEGACY_MANIFEST_PATHS.scenarioIndex));
      return true;
    }
  );
});

test('a fetch that throws is treated as an absent manifest, not a crash', async () => {
  const twin = await loadTwin(async path => {
    if (path === TWIN_CATALOG_PATH) return jsonResponse(catalog());
    throw new Error('network down');
  });
  assert.equal(twin.scenarios.length, 1);
});
