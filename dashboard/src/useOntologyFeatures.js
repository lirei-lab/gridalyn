import { useEffect, useState } from 'react';

import { ontologySources, ontologySql, toOntologyFeatures } from './ontology';

/**
 * Entities typed by what the twin's ontology says they ARE.
 *
 * A hook rather than an effect inside the app component, for the reason
 * `useDuckDB` is one: the query, its cancellation and its failure handling are
 * a unit, and App.jsx is held under a line ceiling precisely so that units
 * like this live in their own file.
 *
 * Independent of the time slice. A class is a property of the entity, not of
 * the instant, so this does not re-query as the animation advances -- which is
 * also why it is not folded into the existing time-slice effect.
 */
export function useOntologyFeatures(db, semantic, scenarioId, enabled) {
  const [features, setFeatures] = useState([]);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      const sources = ontologySources(semantic, scenarioId);
      if (!db || !enabled || sources.length === 0) {
        setFeatures([]);
        return;
      }
      try {
        const conn = await db.connect();
        const collected = [];
        for (const source of sources) {
          const result = await conn.query(ontologySql(source));
          collected.push(...toOntologyFeatures(result.toArray()));
        }
        conn.close();
        if (!cancelled) setFeatures(collected);
      } catch (err) {
        // Surfaced, not silent: an empty class layer and a failed query look
        // identical on the map, and only one of them is the twin's answer.
        console.error('[Ontology] query failed:', err.message || err);
        if (!cancelled) setFeatures([]);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [db, semantic, scenarioId, enabled]);

  return features;
}
