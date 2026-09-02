import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  GEOMETRY_FIELD,
  GEOMETRY_LINE,
  GEOMETRY_POINT,
  MAP_LAYERS,
  SOURCE_ONTOLOGY,
  UNSUPPORTED_GEOMETRIES,
  buildLayers,
  describeFeature,
  describeLayers,
  loadingColor,
  ontologyClassColors,
  ontologyLayers,
  registryFor,
} from './mapLayers.js';

const EMPTY = { nodes: [], lines: [], transformers: [] };

function ids(heatmapMode) {
  return buildLayers({
    features: EMPTY,
    heatmapMode,
    onSelectNode() {},
  }).map(layer => layer.id);
}

test('every registry entry declares the four things a layer model needs', () => {
  for (const layer of MAP_LAYERS) {
    assert.ok(layer.id, 'layer has an id');
    assert.ok(layer.label, `${layer.id} has a label`);
    assert.ok(
      [GEOMETRY_LINE, GEOMETRY_POINT, GEOMETRY_FIELD].includes(layer.geometry),
      `${layer.id} declares a known geometry, got ${layer.geometry}`
    );
    assert.equal(typeof layer.visible, 'function', `${layer.id} declares visibility`);
    assert.equal(typeof layer.build, 'function', `${layer.id} can be built`);
  }
});

test('layer ids are unique, because deck.gl keys on them', () => {
  const seen = MAP_LAYERS.map(layer => layer.id);
  assert.equal(new Set(seen).size, seen.length, `duplicate layer id in ${seen}`);
});

test('the base layers are always drawn', () => {
  for (const mode of ['nodes', 'lines', 'transformers', null]) {
    const drawn = ids(mode);
    assert.ok(drawn.includes('grid-lines-layer'), `cables missing at ${mode}`);
    assert.ok(drawn.includes('scatter-nodes-layer'), `buses missing at ${mode}`);
    assert.ok(
      drawn.includes('transformer-markers-layer'),
      `transformers missing at ${mode}`
    );
  }
});

test('the heat field follows the selected mode', () => {
  assert.ok(ids('nodes').includes('heatmap-nodes-layer'));
  assert.ok(ids('lines').includes('heatmap-nodes-layer'));
  assert.ok(!ids('transformers').includes('heatmap-nodes-layer'));
  assert.ok(!ids(null).includes('heatmap-nodes-layer'));
});

test('transformer stress layers appear only in transformer mode', () => {
  const on = ids('transformers');
  assert.ok(on.includes('transformer-loading-heatmap-layer'));
  assert.ok(on.includes('transformer-overload-halo-layer'));
  for (const mode of ['nodes', 'lines', null]) {
    assert.ok(!ids(mode).includes('transformer-loading-heatmap-layer'));
    assert.ok(!ids(mode).includes('transformer-overload-halo-layer'));
  }
});

test('a hidden layer is not built at all', () => {
  // It used to be instantiated with `data: []`, which says "this layer has no
  // data" -- a different statement from "this layer is not shown".
  assert.equal(ids(null).length, 3);
  assert.equal(ids('transformers').length, 5);
});

test('the registry can be described without drawing anything', () => {
  const described = describeLayers({ heatmapMode: 'nodes' });
  assert.equal(described.length, MAP_LAYERS.length);
  const field = described.find(layer => layer.id === 'heatmap-nodes-layer');
  assert.equal(field.geometry, GEOMETRY_FIELD);
  assert.equal(field.source, 'nodes');
  assert.equal(field.visible, true);
  assert.equal(
    described.find(layer => layer.id === 'transformer-overload-halo-layer').visible,
    false
  );
});

test('loading colour keeps its four thermal bands', () => {
  assert.deepEqual(loadingColor(120), [255, 0, 40, 220]);
  assert.deepEqual(loadingColor(90), [255, 100, 0, 220]);
  assert.deepEqual(loadingColor(60), [255, 200, 0, 220]);
  assert.deepEqual(loadingColor(10), [0, 190, 210, 220]);
  assert.deepEqual(loadingColor(120, 245), [255, 0, 40, 245]);
});

test('a feature describes itself by what it is, not by the layer that hit it', () => {
  assert.match(
    describeFeature({
      properties: { trafo_idx: 7, transformer_kind: 'HV/MV', loading_percent: 91.25, sn_mva: 2.5 },
    }),
    /Transformer: 7 \| HV\/MV \| Load: 91\.3% \| Rating: 2\.50 MVA/
  );
  assert.match(
    describeFeature({ properties: { line_idx: 3, loading_percent: 42.4, category: 'LV' } }),
    /Cable: 3 \| Load: 42\.4% \| Cat: LV/
  );
  assert.match(
    describeFeature({ properties: { bus_idx: 11, vm_pu: 0.9871, category: 'MV' } }),
    /Bus: 11 \| Voltage: 0\.987 p\.u\. \| Cat: MV/
  );
});

test('describeFeature returns null for nothing hovered', () => {
  assert.equal(describeFeature(null), null);
  assert.equal(describeFeature({}), null);
  assert.equal(describeFeature({ properties: { unrelated: 1 } }), null);
});

test('clicking a bus selects it and clicking empty space clears it', () => {
  let selected = 'unset';
  const [, buses] = buildLayers({
    features: EMPTY,
    heatmapMode: null,
    onSelectNode: value => {
      selected = value;
    },
  });
  const feature = { properties: { bus_idx: 4 } };
  buses.props.onClick({ object: feature });
  assert.equal(selected, feature);
  buses.props.onClick({ object: null });
  assert.equal(selected, null);
  // A picked object that is not a bus must clear too, not select a half-object.
  buses.props.onClick({ object: { properties: { line_idx: 1 } } });
  assert.equal(selected, null);
});

/** The drawable classes the tracked catalog declares -- read, never named. */
const SHIPPED_DRAWABLE_CLASSES = [
  ...new Set(
    JSON.parse(
      readFileSync(
        join(
          dirname(fileURLToPath(import.meta.url)),
          '..',
          '..',
          'instances',
          'default',
          'digital_twin',
          'dashboard',
          'catalog.json'
        ),
        'utf8'
      )
    )
      .semantic.classes.filter(entry => entry.located && entry.coordinates)
      .map(entry => entry.class)
  ),
];

const ONTOLOGY_CONTEXT = {
  features: { ...EMPTY, ontology: [] },
  heatmapMode: null,
  onSelectNode() {},
  showOntology: true,
  ontologyClasses: [
    { name: 'Building', located: true },
    { name: 'EVChargingAsset', located: true },
  ],
};

test('the registry gains a layer per declared class, not per coded name', () => {
  const drawn = buildLayers(ONTOLOGY_CONTEXT).map(layer => layer.id);
  assert.ok(drawn.includes('ontology-class-Building-layer'));
  assert.ok(drawn.includes('ontology-class-EVChargingAsset-layer'));
});

test('a class this file has never heard of still reaches the map', () => {
  // The property the catalog exists to win: adding an ontology class to the
  // twin must not need a dashboard edit. Nothing in mapLayers.js names a class.
  const drawn = buildLayers({
    ...ONTOLOGY_CONTEXT,
    ontologyClasses: [{ name: 'brick:Laboratory', located: true }],
  }).map(layer => layer.id);
  assert.ok(drawn.includes('ontology-class-brick-Laboratory-layer'), drawn.join(', '));
});

test('a class the twin cannot locate is not drawn in the wrong place', () => {
  const drawn = buildLayers({
    ...ONTOLOGY_CONTEXT,
    ontologyClasses: [{ name: 'ACLineSegment', located: false }],
  }).map(layer => layer.id);
  assert.ok(!drawn.some(id => id.startsWith('ontology-class-')));
});

test('the ontology layers appear only when asked for', () => {
  const off = buildLayers({ ...ONTOLOGY_CONTEXT, showOntology: false });
  assert.equal(off.length, 3, 'only the three always-on electrical layers');
  assert.ok(!off.some(layer => layer.id.startsWith('ontology-class-')));
});

test('a single class can be isolated without the others being rebuilt', () => {
  const drawn = buildLayers({
    ...ONTOLOGY_CONTEXT,
    ontologyClass: 'EVChargingAsset',
  }).map(layer => layer.id);
  assert.ok(drawn.includes('ontology-class-EVChargingAsset-layer'));
  assert.ok(!drawn.includes('ontology-class-Building-layer'));
});

test('a derived layer draws only its own class', () => {
  const features = {
    ...EMPTY,
    ontology: [
      { geometry: { coordinates: [0, 0] }, properties: { ontology_class: 'Building' } },
      {
        geometry: { coordinates: [1, 1] },
        properties: { ontology_class: 'EVChargingAsset' },
      },
    ],
  };
  const [layer] = buildLayers({ ...ONTOLOGY_CONTEXT, features }).filter(
    entry => entry.id === 'ontology-class-EVChargingAsset-layer'
  );
  assert.equal(layer.props.data.length, 1);
  assert.equal(layer.props.data[0].properties.ontology_class, 'EVChargingAsset');
});

test('class colours are stable for a fixed set of classes', () => {
  const names = ['Alpha', 'Beta', 'Gamma'];
  const first = ontologyClassColors(names);
  const again = ontologyClassColors([...names].reverse());
  // Order-independent: the assignment sorts, so the catalog's listing order
  // cannot change what a class draws as.
  for (const name of names) {
    assert.deepEqual(first.get(name), again.get(name));
  }
  for (const channel of first.get('Alpha')) {
    assert.ok(Number.isInteger(channel) && channel >= 0 && channel <= 255);
  }
});

test('colours are distinct while the palette allows it', () => {
  // The defect running the app exposed: hashing alone gave the two most
  // numerous drawable classes of the shipped twin the same slot, and the map
  // read as monochrome. Probing resolves the clash.
  const shipped = ontologyClassColors(SHIPPED_DRAWABLE_CLASSES);
  const rendered = new Set([...shipped.values()].map(String));
  assert.equal(
    rendered.size,
    SHIPPED_DRAWABLE_CLASSES.length,
    `two classes share a colour: ${[...shipped].map(([k, v]) => k + '=' + v)}`
  );
});

test('more classes than palette slots still all draw', () => {
  const many = Array.from({ length: 20 }, (_, index) => `class-${index}`);
  const colors = ontologyClassColors(many);
  assert.equal(colors.size, many.length);
  for (const name of many) assert.equal(colors.get(name).length, 4);
});

test('a class this file has never heard of still gets a colour', () => {
  const colors = ontologyClassColors(['brick:Laboratory']);
  assert.equal(colors.get('brick:Laboratory').length, 4);
});

test('the derived entries declare everything the registry model requires', () => {
  const derived = ontologyLayers(ONTOLOGY_CONTEXT);
  assert.equal(derived.length, 2);
  for (const layer of derived) {
    assert.ok(layer.id);
    assert.equal(layer.label, layer.ontologyClass);
    assert.equal(layer.geometry, GEOMETRY_POINT);
    assert.equal(layer.source, SOURCE_ONTOLOGY);
    assert.equal(typeof layer.visible, 'function');
    assert.equal(typeof layer.build, 'function');
    assert.equal(layer.derived, true);
  }
});

test('derived layers are described alongside the coded ones', () => {
  const described = describeLayers(ONTOLOGY_CONTEXT);
  assert.equal(described.length, MAP_LAYERS.length + 2);
  const evse = described.find(layer => layer.ontologyClass === 'EVChargingAsset');
  assert.equal(evse.derived, true);
  assert.equal(evse.visible, true);
  assert.equal(described.find(layer => layer.id === 'grid-lines-layer').derived, false);
});

test('derived layer ids stay unique across the whole registry', () => {
  const ids = registryFor(ONTOLOGY_CONTEXT).map(layer => layer.id);
  assert.equal(new Set(ids).size, ids.length, `duplicate layer id in ${ids}`);
  // A class declared twice -- once per artifact -- must not produce two layers
  // with the same deck.gl id.
  const doubled = registryFor({
    ...ONTOLOGY_CONTEXT,
    ontologyClasses: [
      { name: 'Building', located: true },
      { name: 'Building', located: true },
    ],
  }).map(layer => layer.id);
  assert.equal(new Set(doubled).size, doubled.length);
});

test('an ontology feature describes itself by its class, then its id', () => {
  assert.equal(
    describeFeature({
      properties: { ontology_class: 'EVChargingAsset', entity_id: 'building:4' },
    }),
    'EVChargingAsset: building:4'
  );
  assert.match(
    describeFeature({ properties: { ontology_class: 'Building', entity_id: null } }),
    /Building: unidentified/
  );
});

test('no layer draws geometry the twin does not hold', () => {
  // The twin's `buildings` geometry is POINTS -- the ingest keeps the centroid
  // and drops the footprint -- and the catalog declares it. An ontology-typed
  // building layer is the first thing a reader would expect to draw as actual
  // building shapes, which is exactly why this is guarded rather than assumed.
  const registry = registryFor(ONTOLOGY_CONTEXT);
  for (const layer of registry) {
    assert.ok(
      !UNSUPPORTED_GEOMETRIES.includes(layer.geometry),
      `${layer.id} declares ${layer.geometry}, which the twin does not carry`
    );
  }
  // deck.gl polygon classes would bypass the declaration above, so the
  // instantiated layers are checked too.
  for (const layer of buildLayers(ONTOLOGY_CONTEXT)) {
    assert.ok(
      !/polygon/i.test(layer.constructor.name),
      `${layer.id} is a ${layer.constructor.name}; buildings are points here`
    );
  }
});
