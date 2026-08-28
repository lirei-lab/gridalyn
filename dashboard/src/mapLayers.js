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

/** Which of the twin's artifacts a layer reads. */
export const SOURCE_NODES = 'nodes';
export const SOURCE_LINES = 'lines';
export const SOURCE_TRANSFORMERS = 'transformers';

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

/** Describe the registry without building anything, for a legend or a toggle. */
export function describeLayers(context = { heatmapMode: null }) {
  return MAP_LAYERS.map(layer => ({
    id: layer.id,
    label: layer.label,
    geometry: layer.geometry,
    source: layer.source,
    visible: layer.visible(context),
  }));
}

/** Build the deck.gl layers the context makes visible, in registry order. */
export function buildLayers(context) {
  return MAP_LAYERS.filter(layer => layer.visible(context)).map(layer =>
    layer.build(context)
  );
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
  return null;
}
