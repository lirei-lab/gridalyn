import assert from 'node:assert/strict';
import test from 'node:test';

import {
  artifactAlias,
  describeOntologyClasses,
  drawableClasses,
  ontologySources,
  ontologySql,
  toOntologyFeatures,
} from './ontology.js';

const COORDS = { latitude: 'lat', longitude: 'lon' };

function semantic(overrides = {}) {
  return {
    profile: 'north_america',
    classes: [
      {
        name: 'Building',
        count: 2911,
        population: 'scenario_assets',
        artifact: 'asset_registry',
        column: 'ontology_class',
        located: true,
        coordinates: COORDS,
        identity: 'building_id',
        scenarioColumn: 'scenario_id',
        scenarioId: 'S1',
      },
      {
        name: 'EVChargingAsset',
        count: 324,
        population: 'scenario_assets',
        artifact: 'asset_registry',
        column: 'ontology_class',
        located: true,
        coordinates: COORDS,
        identity: 'building_id',
        scenarioColumn: 'scenario_id',
        scenarioId: 'S1',
      },
      {
        name: 'ACLineSegment',
        count: 3398,
        population: 'base_snapshot',
        artifact: 'grid_lines',
        column: 'cim_class',
        located: false,
        coordinates: null,
        identity: 'line_id',
        scenarioColumn: null,
        scenarioId: null,
      },
      {
        name: 'ConnectivityNode',
        count: 3562,
        population: 'base_snapshot',
        artifact: 'grid_buses',
        column: 'cim_class',
        located: true,
        coordinates: COORDS,
        identity: 'bus_id',
        scenarioColumn: null,
        scenarioId: null,
      },
    ],
    ...overrides,
  };
}

test('only classes the twin says are located are drawable', () => {
  const names = drawableClasses(semantic(), 'S1').map(entry => entry.name);
  // ACLineSegment is excluded because the twin declares its geometry derived
  // from bus endpoints, not because this file knows what a line is.
  assert.deepEqual(names, ['Building', 'EVChargingAsset', 'ConnectivityNode']);
});

test('a scenario sees its own classes and the unscoped ones, not a sibling scenario', () => {
  const names = drawableClasses(semantic(), 'S4').map(entry => entry.name);
  assert.deepEqual(names, ['ConnectivityNode']);
});

test('classes are grouped into one query per artifact', () => {
  const sources = ontologySources(semantic(), 'S1');
  assert.deepEqual(
    sources.map(source => [source.artifact, source.classes]),
    [
      ['asset_registry', ['Building', 'EVChargingAsset']],
      ['grid_buses', ['ConnectivityNode']],
    ]
  );
  assert.equal(sources[0].alias, artifactAlias('asset_registry'));
});

test('the SQL reads the columns the twin declared, never an assumed spelling', () => {
  const registry = ontologySources(semantic(), 'S1')[0];
  const sql = ontologySql(registry);
  assert.match(sql, /"ontology_class" AS ontology_class/);
  assert.match(sql, /"lon" AS lon/);
  assert.match(sql, /"building_id" AS entity_id/);
  assert.match(sql, /"scenario_id" = 'S1'/);
  assert.match(sql, /FROM 'asset_registry\.parquet'/);
});

test('a twin that spells its columns differently is read differently', () => {
  // The whole point of declaring the columns: this client writes no literal
  // `lat`, `lon`, `ontology_class` or `scenario_id` anywhere.
  const odd = semantic({
    classes: [
      {
        name: 'School',
        count: 3,
        population: 'base_snapshot',
        artifact: 'premises',
        column: 'brick_class',
        located: true,
        coordinates: { latitude: 'y_deg', longitude: 'x_deg' },
        identity: 'premise_urn',
        scenarioColumn: null,
        scenarioId: null,
      },
    ],
  });
  const sql = ontologySql(ontologySources(odd, 'S1')[0]);
  assert.match(sql, /"brick_class" AS ontology_class/);
  assert.match(sql, /"x_deg" AS lon/);
  assert.match(sql, /"y_deg" AS lat/);
  assert.match(sql, /"premise_urn" AS entity_id/);
  assert.ok(!/scenario/.test(sql), `unscoped artifact must not be filtered: ${sql}`);
});

test('an artifact with no identity column still queries, saying so', () => {
  const anonymous = semantic({
    classes: [
      {
        ...semantic().classes[0],
        identity: null,
      },
    ],
  });
  assert.match(ontologySql(ontologySources(anonymous, 'S1')[0]), /NULL AS entity_id/);
});

test('a class name with an apostrophe cannot break the query', () => {
  const quoted = semantic({
    classes: [{ ...semantic().classes[0], name: "Farmer's Market" }],
  });
  assert.match(
    ontologySql(ontologySources(quoted, 'S1')[0]),
    /IN \('Farmer''s Market'\)/
  );
});

test('rows become features in the shape the layer registry draws', () => {
  const features = toOntologyFeatures([
    { ontology_class: 'EVChargingAsset', lon: -72.6, lat: 46.3, entity_id: 'building:4' },
  ]);
  assert.deepEqual(features[0].geometry.coordinates, [-72.6, 46.3]);
  assert.equal(features[0].properties.ontology_class, 'EVChargingAsset');
  assert.equal(features[0].properties.entity_id, 'building:4');
});

test('a class the map cannot draw is reported with the reason, not omitted', () => {
  const described = describeOntologyClasses(semantic(), 'S1');
  const line = described.find(entry => entry.name === 'ACLineSegment');
  assert.equal(line.drawable, false);
  assert.match(line.undrawableReason, /grid_lines carries no coordinates/);
  assert.equal(described.find(entry => entry.name === 'Building').undrawableReason, null);
});

test('a twin with no ontology yields nothing rather than throwing', () => {
  assert.deepEqual(drawableClasses(null), []);
  assert.deepEqual(ontologySources(null), []);
  assert.deepEqual(describeOntologyClasses(null), []);
});

test('the pre-catalog four-scalar shape degrades instead of crashing', () => {
  // The fallback still hands the panel `{profile, nodeCount, edgeCount, valid}`
  // with no `classes`, because a twin without a catalog has no other route to
  // its profile. That shape must produce an empty class list, not a throw.
  const legacy = {
    profile: 'north_america',
    nodeCount: 74286,
    edgeCount: 147065,
    valid: true,
    manifestPath: '/instances/default/digital_twin/semantic/graph_manifest.json',
    artifacts: {},
  };
  assert.deepEqual(describeOntologyClasses(legacy, 'S0'), []);
  assert.deepEqual(drawableClasses(legacy, 'S0'), []);
  assert.deepEqual(ontologySources(legacy, 'S0'), []);
});

test('a class with no coordinates is refused even when located claims true', () => {
  // `located` and `coordinates` are two statements from the twin, and only the
  // second is enough to build a query. Drawing on the first alone would mean
  // assuming lat/lon, which is what the declaration removed.
  const inconsistent = {
    classes: [
      {
        name: 'Building',
        count: 1,
        population: 'base_snapshot',
        artifact: 'buildings',
        column: 'ontology_class',
        located: true,
        coordinates: null,
        identity: 'building_id',
        scenarioColumn: null,
        scenarioId: null,
      },
    ],
  };
  assert.deepEqual(drawableClasses(inconsistent), []);
});

test('the scenario filter is applied from the DECLARED column', () => {
  // Regression: `scenario_column` was published but not read, so the query
  // came out unscoped and drew every scenario's rows at once -- five stacked
  // copies of the same 3235 buildings.
  const sql = ontologySql(ontologySources(semantic(), 'S1')[0]);
  assert.match(sql, /"scenario_id" = 'S1'/);
});

test('one artifact per entity namespace: the most specific reading wins', () => {
  // Measured on the shipped twin: `buildings` and `asset_registry` both key on
  // `building_id`, so querying both drew all 3235 buildings twice, and drew a
  // scenario's EV charging assets a second time as plain buildings underneath.
  const overlapping = semantic({
    classes: [
      {
        name: 'Building',
        count: 3235,
        population: 'base_snapshot',
        artifact: 'buildings',
        column: 'ontology_class',
        located: true,
        coordinates: COORDS,
        identity: 'building_id',
        scenarioColumn: null,
        scenarioId: null,
      },
      ...semantic().classes.filter(entry => entry.artifact === 'asset_registry'),
      ...semantic().classes.filter(entry => entry.artifact === 'grid_buses'),
    ],
  });
  const artifacts = ontologySources(overlapping, 'S1').map(s => s.artifact);
  // The scenario-scoped reading of `building_id` supersedes the base one; the
  // bus namespace is untouched because nothing else keys on `bus_id`.
  assert.deepEqual(artifacts, ['asset_registry', 'grid_buses']);
});

test('superseding for the map does not hide a class from the legend', () => {
  const overlapping = semantic({
    classes: [
      {
        ...semantic().classes[0],
        artifact: 'buildings',
        scenarioColumn: null,
        scenarioId: null,
        count: 3235,
      },
      ...semantic().classes,
    ],
  });
  const described = describeOntologyClasses(overlapping, 'S1');
  assert.equal(
    described.filter(entry => entry.name === 'Building').length,
    2,
    'the legend reports every class the twin declares, both readings'
  );
});

test('an artifact with no declared identity is its own namespace', () => {
  // Nothing can be matched against it, so it must never be superseded away.
  const anonymous = semantic({
    classes: [
      { ...semantic().classes[0], artifact: 'a', identity: null },
      { ...semantic().classes[1], artifact: 'b', identity: null },
    ],
  });
  assert.deepEqual(
    ontologySources(anonymous, 'S1').map(s => s.artifact),
    ['a', 'b']
  );
});
