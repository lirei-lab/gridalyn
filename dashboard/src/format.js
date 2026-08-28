/**
 * Number and label formatting shared across the dashboard's panels.
 *
 * Small, but worth its own module: these were defined inside App.jsx, so any
 * panel extracted from it either had to import from the app component -- a
 * cycle -- or re-implement them and drift.
 *
 * Carried over byte-for-byte from App.jsx, sentinel and thresholds included.
 * This is a restructuring, so `'n/a'` stays `'n/a'` and `signedFmt` keeps
 * printing no sign for exactly zero.
 */

/** Format a number to fixed digits, or `'n/a'` when there is nothing to show. */
export function fmt(value, digits = 2) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) {
    return 'n/a';
  }
  return Number(value).toFixed(digits);
}

/** Like {@link fmt}, but prefixes a `+` so a positive delta reads as signed. */
export function signedFmt(value, digits = 2) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) {
    return 'n/a';
  }
  const number = Number(value);
  return `${number > 0 ? '+' : ''}${number.toFixed(digits)}`;
}

/** Human title for a heatmap mode id. */
export function heatmapTitle(mode) {
  if (mode === 'nodes') return 'Nodal Voltage Drop';
  if (mode === 'lines') return 'Cable Thermal Overload';
  return 'Transformer Thermal Overload';
}
