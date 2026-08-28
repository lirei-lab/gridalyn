/**
 * Where the map opens, derived from the twin rather than hardcoded.
 *
 * `INITIAL_VIEW_STATE` used to carry longitude -72.604 / latitude 46.342 /
 * zoom 14.5 as literals -- the centroid of one particular twin, hand-copied.
 * Point the dashboard at a different network and the map opened over the wrong
 * place with no indication why. The catalog now publishes the extent, so the
 * viewport is computed from it.
 */

/** Used only when the twin declares no extent. Whole-world, deliberately. */
export const UNLOCATED_VIEW_STATE = {
  longitude: 0,
  latitude: 0,
  zoom: 1,
  pitch: 0,
  bearing: 0,
};

export const DEFAULT_PITCH = 45;
export const DEFAULT_BEARING = -10;

/** Fraction of the viewport left as margin around the network's extent. */
const PADDING = 0.12;

const MIN_ZOOM = 1;
const MAX_ZOOM = 18;

/**
 * Zoom at which a span of `degrees` fills `pixels` of viewport.
 *
 * Web-Mercator tiles are 512px and cover 360° of longitude at zoom 0, so a
 * span of d degrees fits a viewport of w pixels at log2((w / 512) * (360 / d)).
 * Latitude is converted to its longitude equivalent by dividing by cos(lat):
 * a degree of longitude shrinks toward the poles, so ignoring it would zoom in
 * too far on a high-latitude network. Quebec sits near 46°, where the factor is
 * already 1.44 -- not a rounding difference.
 */
function zoomForSpan(degrees, pixels) {
  if (!(degrees > 0) || !(pixels > 0)) return MAX_ZOOM;
  return Math.log2((pixels / 512) * (360 / degrees));
}

/**
 * Compute the view state that frames a twin's extent.
 *
 * @param {object|null} geography - the catalog's geography block as read by
 *   `readGeography`; `null` or unlocated yields {@link UNLOCATED_VIEW_STATE}.
 * @param {{width?: number, height?: number}} [viewport] - viewport size in CSS
 *   pixels. Defaults are a typical desktop window; the shape of the answer does
 *   not depend on getting them exactly right, only the final zoom does.
 */
export function viewStateForGeography(geography, viewport = {}) {
  if (!geography?.located || !geography.bbox || !geography.center) {
    return UNLOCATED_VIEW_STATE;
  }
  const { width = 1280, height = 800 } = viewport;
  const [minLon, minLat, maxLon, maxLat] = geography.bbox;
  const { lon, lat } = geography.center;

  const lonSpan = Math.abs(maxLon - minLon);
  // Guard the pole case rather than dividing by a cosine that reaches zero.
  const cosLat = Math.max(Math.cos((lat * Math.PI) / 180), 1e-6);
  const latSpanAsLon = Math.abs(maxLat - minLat) / cosLat;

  // The binding dimension wins: fitting the wider span guarantees the narrower
  // one fits too, where averaging the two would clip the network.
  const zoom = Math.min(
    zoomForSpan(lonSpan, width * (1 - PADDING)),
    zoomForSpan(latSpanAsLon, height * (1 - PADDING))
  );

  return {
    longitude: lon,
    latitude: lat,
    // A degenerate extent -- one bus, or every bus at one point -- makes the
    // span zero and the zoom infinite. Clamped rather than special-cased, so
    // a nearly-degenerate extent behaves like a degenerate one.
    zoom: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom)),
    pitch: DEFAULT_PITCH,
    bearing: DEFAULT_BEARING,
  };
}
