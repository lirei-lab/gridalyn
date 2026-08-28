import assert from 'node:assert/strict';
import test from 'node:test';

import {
  DEFAULT_BEARING,
  DEFAULT_PITCH,
  UNLOCATED_VIEW_STATE,
  viewStateForGeography,
} from './viewState.js';

/** The committed twin: Trois-Rivieres, as the catalog publishes it. */
const QUEBEC = {
  located: true,
  bbox: [-72.62038121024402, 46.33148489812852, -72.5877819981624, 46.354373975078275],
  center: { lon: -72.6040816042032, lat: 46.3429294366034 },
};

test('the map opens on the twin centre the catalog computes', () => {
  const view = viewStateForGeography(QUEBEC);
  assert.equal(view.longitude, QUEBEC.center.lon);
  assert.equal(view.latitude, QUEBEC.center.lat);
  assert.equal(view.pitch, DEFAULT_PITCH);
  assert.equal(view.bearing, DEFAULT_BEARING);
});

test('the zoom frames the committed twin at a plausible street scale', () => {
  // The literal it replaces was 14.5, hand-picked for this one network. The
  // derived value is slightly wider because it fits the WHOLE extent plus a
  // margin, where the literal cropped it.
  const { zoom } = viewStateForGeography(QUEBEC);
  assert.ok(zoom > 12 && zoom < 15, `expected a street-scale zoom, got ${zoom}`);
});

test('a larger network zooms out, a smaller one zooms in', () => {
  const wide = viewStateForGeography({
    located: true,
    bbox: [-73.0, 46.0, -72.4, 46.5],
    center: { lon: -72.7, lat: 46.25 },
  });
  const tight = viewStateForGeography({
    located: true,
    bbox: [-72.605, 46.342, -72.603, 46.344],
    center: { lon: -72.604, lat: 46.343 },
  });
  assert.ok(wide.zoom < viewStateForGeography(QUEBEC).zoom);
  assert.ok(tight.zoom > viewStateForGeography(QUEBEC).zoom);
});

test('the binding dimension wins, so the network is never clipped', () => {
  // A wide, short extent must be framed by its WIDTH. Averaging the two spans
  // would zoom in past the east and west edges.
  const wide = viewStateForGeography({
    located: true,
    bbox: [-10, 45, 10, 45.1],
    center: { lon: 0, lat: 45.05 },
  });
  const tall = viewStateForGeography({
    located: true,
    bbox: [-0.1, 40, 0.1, 50],
    center: { lon: 0, lat: 45 },
  });
  assert.ok(wide.zoom < 7, `a 20-degree-wide extent must zoom out, got ${wide.zoom}`);
  assert.ok(tall.zoom < 7, `a 10-degree-tall extent must zoom out, got ${tall.zoom}`);
});

test('latitude is converted to its longitude equivalent', () => {
  // A degree of longitude shrinks toward the poles, so a tall extent at 80N is
  // physically far narrower than the same degree span at the equator and must
  // zoom differently. The spans are chosen so HEIGHT is the binding dimension
  // in both cases -- with a wide lon span the longitude term wins everywhere
  // and the conversion is never exercised, which is how an earlier version of
  // this test passed the same zoom for both and proved nothing.
  const tall = lat => ({
    located: true,
    bbox: [-0.05, lat - 0.25, 0.05, lat + 0.25],
    center: { lon: 0, lat },
  });
  const equator = viewStateForGeography(tall(0));
  const polar = viewStateForGeography(tall(80));
  assert.notEqual(
    equator.zoom,
    polar.zoom,
    'the cosine correction is not being applied'
  );
  assert.ok(
    polar.zoom < equator.zoom,
    `the height binds harder near the pole (${polar.zoom} vs ${equator.zoom})`
  );
});

test('an unlocated twin opens on the world rather than on null island', () => {
  // The old literal would have put every unlocated twin over Quebec. Zero/zero
  // at zoom 1 says "we do not know where this is", which is the truth.
  assert.deepEqual(viewStateForGeography(null), UNLOCATED_VIEW_STATE);
  assert.deepEqual(viewStateForGeography({ located: false }), UNLOCATED_VIEW_STATE);
  assert.deepEqual(
    viewStateForGeography({ located: true, bbox: null, center: null }),
    UNLOCATED_VIEW_STATE
  );
});

test('a degenerate extent clamps instead of zooming to infinity', () => {
  // One bus, or every bus at the same point: the span is zero and the naive
  // zoom is Infinity.
  const view = viewStateForGeography({
    located: true,
    bbox: [1, 1, 1, 1],
    center: { lon: 1, lat: 1 },
  });
  assert.ok(Number.isFinite(view.zoom));
  assert.equal(view.zoom, 18);
});

test('the viewport size changes the zoom, not the centre', () => {
  const small = viewStateForGeography(QUEBEC, { width: 640, height: 480 });
  const large = viewStateForGeography(QUEBEC, { width: 2560, height: 1440 });
  assert.ok(large.zoom > small.zoom);
  assert.equal(small.longitude, large.longitude);
  assert.equal(small.latitude, large.latitude);
});
