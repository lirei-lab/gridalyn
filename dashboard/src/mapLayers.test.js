import assert from 'node:assert/strict';
import test from 'node:test';

import {
  GEOMETRY_FIELD,
  GEOMETRY_LINE,
  GEOMETRY_POINT,
  MAP_LAYERS,
  buildLayers,
  describeFeature,
  describeLayers,
  loadingColor,
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
