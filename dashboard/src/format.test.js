import assert from 'node:assert/strict';
import test from 'node:test';

import { fmt, heatmapTitle, signedFmt } from './format.js';

// These moved out of App.jsx unchanged. The tests pin the exact behaviour that
// was there, sentinel included, so the move stays a move.

test('fmt reports absence as n/a rather than as a number', () => {
  for (const absent of [null, undefined, NaN, 'not a number']) {
    assert.equal(fmt(absent), 'n/a');
  }
});

test('fmt keeps two digits by default and honours an explicit width', () => {
  assert.equal(fmt(1.23456), '1.23');
  assert.equal(fmt(1.23456, 4), '1.2346');
  assert.equal(fmt(0), '0.00');
  assert.equal(fmt('3.14159', 3), '3.142');
});

test('signedFmt prefixes a plus only for a strictly positive value', () => {
  assert.equal(signedFmt(1.5), '+1.50');
  assert.equal(signedFmt(-1.5), '-1.50');
  // Zero gets no sign. Carried over deliberately: `> 0`, not `>= 0`.
  assert.equal(signedFmt(0), '0.00');
  assert.equal(signedFmt(null), 'n/a');
});

test('heatmapTitle names each mode', () => {
  assert.equal(heatmapTitle('nodes'), 'Nodal Voltage Drop');
  assert.equal(heatmapTitle('lines'), 'Cable Thermal Overload');
  assert.equal(heatmapTitle('transformers'), 'Transformer Thermal Overload');
});
