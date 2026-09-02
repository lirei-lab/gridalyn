/**
 * The twin's map layers, as a registry rather than a list of inline calls.
 *
 * Six deck.gl layers were instantiated inside App.jsx's render, each mixing
 * four separate concerns: what it draws, where its data comes from, when it is
 * visible, and how values map to colour. Adding a layer meant editing the app
 * component; asking "what can this map show?" meant reading 155 lines.
 *
 * A registry entry answers those separately -- `id`, `geometry`, `source`,
 * `visible(context)`, `build(context)` -- so a layer can be listed, toggled and
 * described without being drawn, and adding one touches this file only.
 *
 * The encodings below are carried over unchanged. Colour thresholds, radii and
 * heatmap weights are the map's tuned behaviour, not incidental detail, and
 * this change is a restructuring: it must not move a single pixel.
 */

import { GeoJsonLayer, ScatterplotLayer } from '@deck.gl/layers';
import { HeatmapLayer } from '@deck.gl/aggregation-layers';

/** What a layer draws, independent of which deck.gl class implements it. */
export const GEOMETRY_LINE = 'line';
export const GEOMETRY_POINT = 'point';
export const GEOMETRY_FIELD = 'field';

/**
 * Geometry kinds no layer here may declare, and why.
 *
 * `polygon` is absent from the list above deliberately, not by omission. The
 * twin's `buildings` geometry is POINTS -- the GeoJSON ingest reads real
 * footprints and keeps only the centroid, and the catalog now says so in
 * `network_model.geography.geometry_kinds`. A footprint layer would draw a
 * shape the twin does not hold, which is a claim about the world rather than
 * a rendering choice. A guard asserts this list stays empty of any layer.
 */
export const UNSUPPORTED_GEOMETRIES = ['polygon', 'multipolygon', 'footprint'];

/** Which of the twin's artifacts a layer reads. */
export const SOURCE_NODES = 'nodes';
export const SOURCE_LINES = 'lines';
export const SOURCE_TRANSFORMERS = 'transformers';
export const SOURCE_ONTOLOGY = 'ontology';

/**
 * Palette the ontology layers draw a class from, by position.
 *
 * Deliberately a palette indexed by a hash of the class NAME, not a map from
 * class name to colour. A lookup table would mean a class the twin declares
 * and this file has never heard of -- a new `ontology_class` value, a
 * different profile, a user's own adapter -- draws in a fallback grey or not
 * at all, which is exactly the coupling the catalog exists to break. Adding a
 * class to the twin must not need a dashboard edit.
 */
const ONTOLOGY_PALETTE = [
  [0, 200, 200],
  [255, 170, 0],
  [180, 120, 255],
  [80, 220, 120],
  [255, 105, 160],
  [120, 180, 255],
  [255, 220, 90],
  [230, 130, 90],
];

/** Cheap, stable string hash. Not cryptographic; only needs to spread names. */
function hashName(name) {
  let hash = 0;
  for (const character of String(name)) {
    hash = (hash * 31 + character.codePointAt(0)) % 0xffffffff;
  }
  return hash;
}

/**
 * Assign each class a palette slot, distinct whenever the palette allows.
 *
 * Hashing alone was not enough, and running the dashboard proved it: the two
 * most numerous drawable classes in the shipped twin hash to the same slot, so
 * they drew in the same green and the map read as monochrome. Three classes
 * into eight slots collide about a third of the time -- bad odds for the case
 * that matters most.
 *
 * So the hash picks a preferred slot and a deterministic linear probe resolves
 * a clash, over the names sorted so the assignment does not depend on the order
 * the catalog happened to list them. Two properties survive: no lookup table,
 * so a class this file has never seen still gets a colour; and a fixed set of
 * classes always gets the same colours.
 *
 * More classes than palette entries is the one case that must still collide;
 * probing wraps and the extra classes reuse slots rather than going undrawn.
 */
export function ontologyClassColors(names, alpha = 200) {
  const unique = [...new Set(names.map(String))].sort();
  const taken = new Map();
  const assigned = new Map();
  for (const name of unique) {
    const preferred = hashName(name) % ONTOLOGY_PALETTE.length;
    let slot = preferred;
    for (let step = 0; step < ONTOLOGY_PALETTE.length; step += 1) {
      const candidate = (preferred + step) % ONTOLOGY_PALETTE.length;
      if (!taken.has(candidate)) {
        slot = candidate;
        break;
      }
    }
    taken.set(slot, name);
    const [red, green, blue] = ONTOLOGY_PALETTE[slot];
    assigned.set(name, [red, green, blue, alpha]);
  }
  return assigned;
}

/** Thermal scale deck.gl interpolates between. Six stops, darkest to critical. */
const THERMAL_RANGE = [
  [25, 100, 255, 60],
  [0, 200, 200, 120],
  [150, 255, 50, 180],
  [255, 200, 0, 200],
  [255, 100, 0, 230],
  [255, 0, 40, 255],
];

const TRANSFORMER_THERMAL_RANGE = [
  [25, 100, 255, 55],
  [0, 200, 200, 110],
  [150, 255, 50, 170],
  [255, 200, 0, 210],
  [255, 100, 0, 235],
  [255, 0, 40, 255],
];

function loadingPercent(feature) {
  return feature.properties.loading_percent || 0;
}

/** Colour a loading percentage on the shared four-band thermal scale. */
export function loadingColor(load, alpha = 220) {
  if (load > 100) return [255, 0, 40, alpha];
  if (load > 80) return [255, 100, 0, alpha];
  if (load > 50) return [255, 200, 0, alpha];
  return [0, 190, 210, alpha];
}

function midpoint(feature) {
  const [start, end] = feature.geometry.coordinates;
  return [(start[0] + end[0]) / 2, (start[1] + end[1]) / 2];
}

/**
 * Every layer this map can draw, keyed by id.
 *
 * `visible` is a predicate over the render context rather than a boolean baked
 * into `data`. The previous form passed an empty array when a layer was off,
 * which reads as "this layer has no data" and is a different statement from
 * "this layer is not shown".
 */
export const MAP_LAYERS = [
  {
    id: 'grid-lines-layer',
    label: 'Cables',
    geometry: GEOMETRY_LINE,
    source: SOURCE_LINES,
    visible: () => true,
    build: ({ features, onHover }) =>
      new GeoJsonLayer({
        id: 'grid-lines-layer',
        data: features.lines,
        pickable: true,
        stroked: false,
        filled: false,
        extruded: false,
        lineWidthScale: 1,
        lineWidthMinPixels: 2,
        getLineColor: feature => {
          const load = loadingPercent(feature);
          if (load > 100) return [255, 0, 40, 255];
          if (load > 80) return [255, 100, 0, 200];
          if (load > 50) return [255, 200, 0, 150];
          return [25, 100, 255, 100];
        },
        getLineWidth: feature => {
          const load = loadingPercent(feature);
          return load > 100 ? 5 : load > 50 ? 3 : 2;
        },
        onHover,
      }),
  },
  {
    id: 'scatter-nodes-layer',
    label: 'Buses',
    geometry: GEOMETRY_POINT,
    source: SOURCE_NODES,
    visible: () => true,
    build: ({ features, onSelectNode }) =>
      new ScatterplotLayer({
        id: 'scatter-nodes-layer',
        data: features.nodes,
        pickable: true,
        autoHighlight: true,
        highlightColor: [255, 255, 0, 200],
        onClick: info =>
          onSelectNode(
            info.object?.properties?.bus_idx !== undefined ? info.object : null
          ),
        getPosition: feature => feature.geometry.coordinates,
        getFillColor: feature =>
          feature.properties.category === 'MV'
            ? [255, 255, 255, 180]
            : [200, 200, 200, 90],
        getRadius: feature => (feature.properties.category === 'MV' ? 12 : 5),
        radiusMinPixels: 2,
        radiusMaxPixels: 6,
      }),
  },
  {
    id: 'heatmap-nodes-layer',
    label: 'Voltage / congestion field',
    geometry: GEOMETRY_FIELD,
    source: SOURCE_NODES,
    visible: ({ heatmapMode }) => heatmapMode === 'nodes' || heatmapMode === 'lines',
    build: ({ features, heatmapMode }) => {
      const onNodes = heatmapMode === 'nodes';
      return new HeatmapLayer({
        id: 'heatmap-nodes-layer',
        data: onNodes ? features.nodes : features.lines,
        pickable: false,
        // Voltage heat sits on the bus; congestion heat emanates from the
        // midpoint of the cable, which has no single position of its own.
        getPosition: feature =>
          onNodes ? feature.geometry.coordinates : midpoint(feature),
        getWeight: feature => {
          if (onNodes) {
            // Squared so an extreme voltage drop dominates the blur rather
            // than averaging away against many healthy buses.
            const drop = Math.max(0, 1.0 - (feature.properties.vm_pu || 1.0));
            return Math.pow(drop * 10, 2);
          }
          const load = loadingPercent(feature);
          return load > 50 ? Math.pow(load / 50, 2) : 0;
        },
        radiusPixels: onNodes ? 60 : 40,
        intensity: onNodes ? 0.8 : 1.5,
        threshold: 0.03,
        colorRange: THERMAL_RANGE,
        aggregation: 'SUM',
      });
    },
  },
  {
    id: 'transformer-loading-heatmap-layer',
    label: 'Transformer loading field',
    geometry: GEOMETRY_FIELD,
    source: SOURCE_TRANSFORMERS,
    visible: ({ heatmapMode }) => heatmapMode === 'transformers',
    build: ({ features }) =>
      new HeatmapLayer({
        id: 'transformer-loading-heatmap-layer',
        data: features.transformers,
        pickable: false,
        getPosition: feature => feature.geometry.coordinates,
        getWeight: feature =>
          Math.pow(Math.max(loadingPercent(feature), 20) / 100, 2.2),
        radiusPixels: 58,
        intensity: 1.25,
        threshold: 0.01,
        colorRange: TRANSFORMER_THERMAL_RANGE,
        aggregation: 'SUM',
      }),
  },
  {
    id: 'transformer-overload-halo-layer',
    label: 'Overloaded transformers',
    geometry: GEOMETRY_POINT,
    source: SOURCE_TRANSFORMERS,
    visible: ({ heatmapMode }) => heatmapMode === 'transformers',
    build: ({ features }) =>
      new ScatterplotLayer({
        id: 'transformer-overload-halo-layer',
        data: features.transformers.filter(feature => loadingPercent(feature) > 100),
        pickable: false,
        stroked: true,
        filled: true,
        getPosition: feature => feature.geometry.coordinates,
        getFillColor: [255, 0, 40, 45],
        getLineColor: [255, 255, 255, 180],
        getLineWidth: 2,
        getRadius: feature =>
          feature.properties.transformer_kind === 'HV/MV' ? 70 : 38,
        radiusMinPixels: 7,
        radiusMaxPixels: 18,
        lineWidthMinPixels: 1,
        lineWidthMaxPixels: 3,
      }),
  },
  {
    id: 'transformer-markers-layer',
    label: 'Transformers',
    geometry: GEOMETRY_POINT,
    source: SOURCE_TRANSFORMERS,
    visible: () => true,
    build: ({ features }) =>
      new ScatterplotLayer({
        id: 'transformer-markers-layer',
        data: features.transformers,
        pickable: true,
        stroked: true,
        filled: true,
        autoHighlight: true,
        highlightColor: [255, 255, 255, 220],
        getPosition: feature => feature.geometry.coordinates,
        getFillColor: feature =>
          loadingColor(
            loadingPercent(feature),
            feature.properties.transformer_kind === 'HV/MV' ? 245 : 210
          ),
        getLineColor: feature =>
          feature.properties.transformer_kind === 'HV/MV'
            ? [255, 255, 255, 255]
            : [20, 20, 20, 230],
        getLineWidth: feature =>
          feature.properties.transformer_kind === 'HV/MV' ? 3 : 1,
        getRadius: feature =>
          feature.properties.transformer_kind === 'HV/MV' ? 45 : 18,
        radiusMinPixels: 3,
        radiusMaxPixels: 14,
        lineWidthMinPixels: 1,
        lineWidthMaxPixels: 3,
      }),
  },
];

/** Layer id for one ontology class, derived from the class's own name. */
export function ontologyLayerId(name) {
  return `ontology-class-${String(name).replace(/[^A-Za-z0-9]+/g, '-')}-layer`;
}

/**
 * Registry entries DERIVED from the ontology classes the catalog declares.
 *
 * The six hand-written entries above are each keyed by an electrical quantity
 * -- voltage, loading, overload. None reads the twin's ontology, though every
 * base table and the scenario asset registry carry a class column and the
 * semantic graph carries the hierarchy behind it. A twin that knows a bus
 * serves a school and not a duplex could not show it.
 *
 * These entries close that. One point layer per class the catalog declares as
 * LOCATED -- `located` is the twin's own statement that the artifact's rows
 * carry coordinates, so a class whose geometry would have to be joined is not
 * silently drawn in the wrong place. Nothing here names a class: the ids, the
 * labels and the colours are all functions of what the catalog said, so a
 * class added to the twin reaches the map with no dashboard edit.
 *
 * These are POINT layers, and the twin is what says so: its geography block
 * declares `buildings` geometry as `point`, with the reason (the ingest keeps
 * the centroid and drops the polygon). They must stay point layers until that
 * declaration changes -- an encoding that implied footprints would be claiming
 * geometry the twin does not hold.
 */
export function ontologyLayers(context = {}) {
  const classes = context.ontologyClasses || [];
  const seen = new Set();
  const entries = [];
  // Colours are assigned over the WHOLE drawn set, not per class, so the
  // assignment can guarantee they differ. The panel colours its swatches from
  // the same call over the same set, which is what keeps legend and map
  // agreeing.
  const colors = ontologyClassColors(
    classes.filter(entry => entry?.located && entry?.name).map(entry => entry.name)
  );
  for (const entry of classes) {
    if (!entry?.located || !entry?.name || seen.has(entry.name)) continue;
    seen.add(entry.name);
    const name = entry.name;
    entries.push({
      id: ontologyLayerId(name),
      label: name,
      geometry: GEOMETRY_POINT,
      source: SOURCE_ONTOLOGY,
      ontologyClass: name,
      derived: true,
      visible: ({ showOntology, ontologyClass }) =>
        Boolean(showOntology) && (!ontologyClass || ontologyClass === name),
      build: ({ features }) =>
        new ScatterplotLayer({
          id: ontologyLayerId(name),
          data: (features.ontology || []).filter(
            feature => feature.properties.ontology_class === name
          ),
          pickable: true,
          stroked: true,
          filled: true,
          autoHighlight: true,
          highlightColor: [255, 255, 255, 220],
          getPosition: feature => feature.geometry.coordinates,
          getFillColor: colors.get(name),
          getLineColor: [10, 10, 10, 200],
          getLineWidth: 1,
          getRadius: 14,
          radiusMinPixels: 3,
          radiusMaxPixels: 10,
          lineWidthMinPixels: 1,
        }),
    });
  }
  return entries;
}

/**
 * Every layer the map can draw for this context: the six coded, then the
 * derived ones.
 *
 * A single sequence rather than two lists a caller has to remember to merge --
 * that is what keeps `describeLayers`, `buildLayers` and the
 * no-layer-outside-the-registry guard covering the derived entries too.
 */
export function registryFor(context = {}) {
  return [...MAP_LAYERS, ...ontologyLayers(context)];
}

/** Describe the registry without building anything, for a legend or a toggle. */
export function describeLayers(context = { heatmapMode: null }) {
  return registryFor(context).map(layer => ({
    id: layer.id,
    label: layer.label,
    geometry: layer.geometry,
    source: layer.source,
    ontologyClass: layer.ontologyClass || null,
    derived: Boolean(layer.derived),
    visible: layer.visible(context),
  }));
}

/** Build the deck.gl layers the context makes visible, in registry order. */
export function buildLayers(context) {
  return registryFor(context)
    .filter(layer => layer.visible(context))
    .map(layer => layer.build(context));
}

/**
 * One-line description of a hovered feature, by what the feature IS.
 *
 * Keyed off the identifying property each source writes rather than off the
 * layer that happened to be hit, so a feature reached through a new layer
 * describes itself without this function changing.
 */
export function describeFeature(object) {
  const properties = object?.properties;
  if (!properties) return null;
  if (properties.trafo_idx !== undefined) {
    return (
      `Transformer: ${properties.trafo_idx} | ${properties.transformer_kind} | ` +
      `Load: ${properties.loading_percent.toFixed(1)}% | ` +
      `Rating: ${properties.sn_mva.toFixed(2)} MVA`
    );
  }
  if (properties.line_idx !== undefined) {
    return (
      `Cable: ${properties.line_idx} | ` +
      `Load: ${properties.loading_percent.toFixed(1)}% | Cat: ${properties.category}`
    );
  }
  if (properties.bus_idx !== undefined) {
    return (
      `Bus: ${properties.bus_idx} | ` +
      `Voltage: ${properties.vm_pu.toFixed(3)} p.u. | Cat: ${properties.category}`
    );
  }
  if (properties.ontology_class !== undefined) {
    // The class is what the twin says this entity IS, so it leads. The id
    // follows it rather than the other way round.
    return (
      `${properties.ontology_class}: ${properties.entity_id ?? 'unidentified'}`
    );
  }
  return null;
}
