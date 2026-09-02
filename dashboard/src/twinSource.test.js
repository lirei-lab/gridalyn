import assert from 'node:assert/strict';
import test from 'node:test';

import {
  LEGACY_MANIFEST_PATHS,
  TWIN_CATALOG_PATH,
  TwinDiscoveryError,
  geometryKind,
  readGeography,
  readNetworkModel,
  readObservation,
  readSemantic,
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

const SEMANTIC = {
  profile: 'north_america',
  graph: {
    node_count: 74286,
    edge_count: 147065,
    validation: { valid: true, errors: 0, warnings: 0 },
  },
  populations: ['base_snapshot', 'semantic_graph', 'scenario_assets'],
  classes: [
    {
      class: 'Building',
      count: 3235,
      population: 'base_snapshot',
      artifact: 'buildings',
      column: 'ontology_class',
      located: true,
      scenario_id: null,
      derived_from: [],
    },
    {
      class: 'brick:Building',
      count: 3235,
      population: 'semantic_graph',
      artifact: 'semantic_nodes',
      column: 'semantic_type',
      located: false,
      scenario_id: null,
      derived_from: ['buildings'],
    },
    {
      class: 'EVChargingAsset',
      count: 324,
      population: 'scenario_assets',
      artifact: 'asset_registry',
      column: 'ontology_class',
      located: true,
      scenario_id: 'S0',
      derived_from: [],
    },
  ],
  classes_absent_reason: null,
  paths: {
    nodes: 'instances/default/digital_twin/semantic/nodes.parquet',
    asset_registry: 'instances/default/digital_twin/scenarios/asset_registry.parquet',
  },
};

function semanticCatalog(overrides = {}) {
  return catalog({ schema_version: '1.3', semantic: SEMANTIC, ...overrides });
}

test('the client declares support for every schema the SDK emits', () => {
  // The 1.1/1.2 gap shipped because these two lists drift silently; 1.3 adds
  // `semantic`, and a client that warns its own repo's catalog is unreadable
  // is worse than one that lags.
  assert.equal(schemaWarning(semanticCatalog()), null);
});

test('readSemantic publishes the classes, not four scalars', () => {
  const semantic = readSemantic(semanticCatalog());
  assert.equal(semantic.profile, 'north_america');
  assert.equal(semantic.nodeCount, 74286);
  assert.equal(semantic.edgeCount, 147065);
  assert.equal(semantic.valid, true);
  assert.equal(semantic.classes.length, 3);
  assert.deepEqual(
    semantic.classes.map(entry => entry.name),
    ['Building', 'brick:Building', 'EVChargingAsset']
  );
});

test('each class says which population it came from, because they differ', () => {
  // `buildings.ontology_class` says "Building"; the graph says
  // "brick:Building" for the same rows. A client told only "the classes"
  // would have to read both files to find that out.
  const semantic = readSemantic(semanticCatalog());
  const byName = Object.fromEntries(semantic.classes.map(e => [e.name, e]));
  assert.equal(byName['Building'].population, 'base_snapshot');
  assert.equal(byName['brick:Building'].population, 'semantic_graph');
  assert.deepEqual(byName['brick:Building'].derivedFrom, ['buildings']);
  assert.equal(byName['EVChargingAsset'].scenarioId, 'S0');
});

test('a client can ask for the classes it can draw without knowing any name', () => {
  const drawable = readSemantic(semanticCatalog()).classes.filter(e => e.located);
  assert.deepEqual(
    drawable.map(e => e.name),
    ['Building', 'EVChargingAsset']
  );
});

test('semantic paths are normalized to servable URLs', () => {
  const semantic = readSemantic(semanticCatalog());
  assert.equal(
    semantic.paths.asset_registry,
    '/instances/default/digital_twin/scenarios/asset_registry.parquet'
  );
});

test('a pre-1.3 catalog reads as null, not as an empty ontology', () => {
  assert.equal(readSemantic(catalog()), null);
  assert.equal(readSemantic(null), null);
});

test('a twin that declares no class says why rather than going quiet', () => {
  const empty = semanticCatalog({
    semantic: { ...SEMANTIC, classes: [], classes_absent_reason: 'no class column' },
  });
  const semantic = readSemantic(empty);
  assert.deepEqual(semantic.classes, []);
  assert.equal(semantic.classesAbsentReason, 'no class column');
});

test('loadTwin reaches the ontology through the catalog, not a hardcoded path', async () => {
  const requested = [];
  const twin = await loadTwin(async path => {
    requested.push(path);
    return path === TWIN_CATALOG_PATH ? jsonResponse(semanticCatalog()) : MISSING;
  });
  assert.equal(twin.semantic.profile, 'north_america');
  // The guard: the semantic manifest belongs to the pre-catalog fallback, and
  // reading it on the live path is what this epic removed.
  assert.ok(!requested.includes(LEGACY_MANIFEST_PATHS.semanticManifest));
  assert.deepEqual(requested, [TWIN_CATALOG_PATH]);
});

test('the fallback still reads the legacy manifests, including the semantic one', async () => {
  const requested = [];
  const twin = await loadTwin(async path => {
    requested.push(path);
    if (path === LEGACY_MANIFEST_PATHS.scenarioIndex) {
      return jsonResponse({ scenarios: [{ scenario_id: 'S0', label: 'Base' }] });
    }
    if (path === LEGACY_MANIFEST_PATHS.semanticManifest) {
      return jsonResponse({ semantic_profile: 'north_america', node_count: 5 });
    }
    return MISSING;
  });
  assert.equal(twin.source, 'legacy-manifests');
  assert.equal(twin.semantic, null);
  assert.equal(twin.scenarios[0].semanticGraph.profile, 'north_america');
  assert.ok(requested.includes(LEGACY_MANIFEST_PATHS.semanticManifest));
});

test('the scenario ontology is narrowed to that scenario', async () => {
  const grown = semanticCatalog();
  grown.scenarios.push({ scenario_id: 'S9', label: 'New', paths: SCENARIO_PATHS });
  const twin = await loadTwin(fetcher({ [TWIN_CATALOG_PATH]: jsonResponse(grown) }));
  const [s0, s9] = twin.scenarios;
  // S0's EV class must not be reported as S9's; the unscoped classes are shared.
  assert.deepEqual(
    s0.semanticGraph.classes.map(e => e.name),
    ['Building', 'brick:Building', 'EVChargingAsset']
  );
  assert.deepEqual(
    s9.semanticGraph.classes.map(e => e.name),
    ['Building', 'brick:Building']
  );
});

const OBSERVATION = {
  provenance: 'simulated',
  provenance_values: ['simulated', 'measured'],
  measured: {
    available: false,
    absent_reason: 'this instance carries no measured observations; the SDK ships the ingest path',
    directory: 'instances/default/digital_twin/observations',
    sources: [],
    entity_join: null,
    columns: ['timestamp', 'entity_id', 'quantity', 'value'],
    quantities: ['voltage_pu'],
    join_columns: ['entity_id', 'bus_id'],
  },
};

function observedCatalog(measured = {}) {
  return catalog({
    schema_version: '1.4',
    semantic: SEMANTIC,
    observation: {
      ...OBSERVATION,
      ...(Object.keys(measured).length ? { provenance: 'measured' } : {}),
      measured: { ...OBSERVATION.measured, ...measured },
    },
    scenarios: [
      { scenario_id: 'S0', label: 'Base', paths: SCENARIO_PATHS, provenance: 'simulated' },
    ],
  });
}

test('the client declares support for the schema that carries observation', () => {
  assert.equal(schemaWarning(observedCatalog()), null);
});

test('an instance with no measured data says so, and says why', () => {
  // "None" must be an answer, not a silence: an absent block would be
  // indistinguishable from a catalog too old to have one.
  const observation = readObservation(observedCatalog());
  assert.equal(observation.measured.available, false);
  assert.match(observation.measured.absentReason, /ships the ingest path/);
  assert.equal(
    observation.measured.directory,
    '/instances/default/digital_twin/observations'
  );
});

test('an instance with no measured data is still labelled simulated, not unknown', () => {
  assert.equal(readObservation(observedCatalog()).provenance, 'simulated');
});

test('measured data flips the instance to a shadow', () => {
  const observation = readObservation(
    observedCatalog({
      available: true,
      absent_reason: null,
      sources: ['instances/default/digital_twin/observations/ami.csv'],
      entity_join: 'instances/default/digital_twin/observations/entity_join.csv',
    })
  );
  assert.equal(observation.provenance, 'measured');
  assert.equal(observation.measured.available, true);
  assert.equal(observation.measured.absentReason, null);
  assert.deepEqual(observation.measured.sources, [
    '/instances/default/digital_twin/observations/ami.csv',
  ]);
  assert.match(observation.measured.entityJoin, /entity_join\.csv$/);
});

test('the export contract travels with the declaration, not restated here', () => {
  const measured = readObservation(observedCatalog()).measured;
  assert.deepEqual(measured.columns, ['timestamp', 'entity_id', 'quantity', 'value']);
  assert.deepEqual(measured.quantities, ['voltage_pu']);
  assert.deepEqual(measured.joinColumns, ['entity_id', 'bus_id']);
});

test('a pre-1.4 catalog reads as null, which is not the same as "none"', () => {
  // The distinction the block exists for: this catalog cannot answer, whereas
  // a 1.4 catalog with no data answers "no".
  assert.equal(readObservation(catalog()), null);
  assert.equal(readObservation(null), null);
});

test('every scenario carries the provenance of its own numbers', async () => {
  const twin = await loadTwin(
    fetcher({ [TWIN_CATALOG_PATH]: jsonResponse(observedCatalog()) })
  );
  assert.equal(twin.scenarios[0].provenance, 'simulated');
  assert.equal(twin.observation.provenance, 'simulated');
});

test('a scenario with no declared provenance falls back to the instance', async () => {
  const undeclared = observedCatalog();
  delete undeclared.scenarios[0].provenance;
  const twin = await loadTwin(
    fetcher({ [TWIN_CATALOG_PATH]: jsonResponse(undeclared) })
  );
  assert.equal(twin.scenarios[0].provenance, 'simulated');
});

test('the fallback cannot state a provenance, and does not invent one', async () => {
  const twin = await loadTwin(
    fetcher({
      [LEGACY_MANIFEST_PATHS.scenarioIndex]: jsonResponse({
        scenarios: [{ scenario_id: 'S0', label: 'Base' }],
      }),
    })
  );
  assert.equal(twin.observation, null);
  assert.equal(twin.scenarios[0].provenance, undefined);
});

test('the twin says what KIND its geometry is, not only that it exists', () => {
  const declared = catalog();
  declared.network_model.geography = {
    ...GEOGRAPHY,
    geometry_kinds: {
      buildings: { kind: 'point', reason: 'the ingest keeps the centroid' },
      grid_buses: { kind: 'point' },
      grid_lines: { kind: 'derived' },
    },
  };
  const geography = readGeography(declared);
  // A coordinate pair says a position exists; it does not say the position is
  // the whole geometry. For buildings it is a reduction of a footprint the
  // twin does not retain, and a client that assumed otherwise would draw one.
  assert.equal(geometryKind(geography, 'buildings').kind, 'point');
  assert.match(geometryKind(geography, 'buildings').reason, /keeps the centroid/);
  assert.equal(geometryKind(geography, 'grid_lines').kind, 'derived');
  assert.equal(geometryKind(geography, 'grid_buses').reason, null);
});

test('an undeclared geometry kind reads as unknown, never as point', () => {
  // A pre-1.4 catalog has not told us the shape, and assuming the one we would
  // prefer to draw is the failure this declaration exists to prevent.
  assert.equal(geometryKind(readGeography(catalog()), 'buildings'), null);
  assert.equal(geometryKind(null, 'buildings'), null);
});

test('readSemantic carries every column the twin declares, not a subset', () => {
  // Regression: `scenario_column` was dropped in this mapping, so the query
  // built from it came out unscoped. The catalog declaring a column is only
  // half of it; the client has to read it.
  const [entry] = readSemantic(
    semanticCatalog({
      semantic: {
        ...SEMANTIC,
        classes: [
          {
            class: 'EVChargingAsset',
            count: 324,
            population: 'scenario_assets',
            artifact: 'asset_registry',
            column: 'ontology_class',
            located: true,
            coordinates: { latitude: 'lat', longitude: 'lon' },
            identity: 'building_id',
            scenario_column: 'scenario_id',
            scenario_id: 'S1',
            derived_from: [],
          },
        ],
      },
    })
  ).classes;
  assert.deepEqual(entry.coordinates, { latitude: 'lat', longitude: 'lon' });
  assert.equal(entry.identity, 'building_id');
  assert.equal(entry.scenarioColumn, 'scenario_id');
  assert.equal(entry.scenarioId, 'S1');
});
