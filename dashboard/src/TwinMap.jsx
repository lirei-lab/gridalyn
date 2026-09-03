import DeckGL from '@deck.gl/react';
import Map from 'react-map-gl/maplibre';

import { buildLayers, describeFeature } from './mapLayers';
import { viewStateForGeography } from './viewState';

/**
 * The twin's geographic view.
 *
 * Extracted from App.jsx, where the map, its six layers, its tooltip and its
 * viewport were interleaved with the control panel and the data loading. It
 * takes the twin's features and geography and draws them; it holds no state,
 * loads nothing, and knows nothing about scenarios or studies.
 *
 * The layers come from the registry in `mapLayers.js`, so adding one does not
 * touch this component either.
 */

/** Carto Dark Matter, the only external asset the map pulls. */
const MAP_STYLE = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';

export default function TwinMap({
  features,
  geography,
  heatmapMode,
  ontologyClasses,
  showOntology,
  onSelectNode,
  children,
}) {
  // Recomputed only when the twin's extent changes, not on every render: deck.gl
  // treats a new initialViewState object as a camera reset, so rebuilding it
  // each render would fight the user's own panning.
  const initialViewState = viewStateForGeography(geography);
  const layers = buildLayers({
    features,
    heatmapMode,
    // The registry derives a layer per declared class from these; this
    // component neither names a class nor knows how many there are.
    ontologyClasses,
    showOntology,
    onSelectNode,
  });

  return (
    <DeckGL
      initialViewState={initialViewState}
      controller={true}
      layers={layers}
      getTooltip={({ object }) => describeFeature(object)}
    >
      {/* MapLibre is the 2D background tile provider under the WebGL overlay. */}
      <Map reuseMaps mapStyle={MAP_STYLE} />
      {children}
    </DeckGL>
  );
}
