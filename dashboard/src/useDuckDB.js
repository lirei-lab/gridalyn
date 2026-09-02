import { useState, useEffect } from 'react';
import * as duckdb from '@duckdb/duckdb-wasm';
import duckdb_wasm from '@duckdb/duckdb-wasm/dist/duckdb-mvp.wasm?url';
import mvp_worker from '@duckdb/duckdb-wasm/dist/duckdb-browser-mvp.worker.js?url';
import { buildScenarioCatalog } from './scenarios';

/**
 * Per-scenario artifact kinds, and the alias each is queried under.
 *
 * Derived by iterating the paths a scenario declares rather than by four
 * copied registration blocks, so a kind added to the twin's catalog becomes
 * queryable without editing this file.
 */
const SCENARIO_FILE_KINDS = ['nodes', 'lines', 'power', 'transformers'];

// Force MVP bundle — does NOT require SharedArrayBuffer
// (EH/pthread bundles can hang on non-HTTPS origins like Tailscale HTTP)
export function useDuckDB(
  scenarios = buildScenarioCatalog(),
  geography = null,
  semantic = null
) {
  const [db, setDb] = useState(null);
  const [isInitializing, setIsInitializing] = useState(true);
  const [dbError, setDbError] = useState(null);
  const scenarioPayload = JSON.stringify({
    scenarios: scenarios.map(scenario => ({
      id: scenario.id,
      paths: scenario.paths,
    })),
    // The twin's base geo tables -- buses, lines, buildings, transformers --
    // registered from what the catalog declares. Without these the map can
    // only draw whatever a scenario's timeseries happens to repeat per
    // timestamp, which is why bus coordinates were duplicated a million rows
    // deep before the catalog named the base layer.
    geoPaths: geography?.paths || {},
    // The ontology's own artifacts -- the scenario asset registry above all,
    // which is the only class population that varies WITHIN an artifact and so
    // the only one a map can encode as a dimension. Filtered to parquet
    // because the semantic block also names JSON documents (the profile, the
    // graph manifest) that DuckDB has no business registering. Registration is
    // lazy -- `registerFileURL` records a URL and DuckDB fetches only what a
    // query touches -- so naming the multi-megabyte node and edge tables here
    // costs nothing until something reads them.
    semanticPaths: Object.fromEntries(
      Object.entries(semantic?.paths || {}).filter(([, path]) =>
        String(path).endsWith('.parquet')
      )
    ),
  });

  useEffect(() => {
    let internalDb = null;
    let cancelled = false;

    async function initializeDuckDB() {
      try {
        const {
          scenarios: scenarioCatalog,
          geoPaths,
          semanticPaths,
        } = JSON.parse(scenarioPayload);
        if (scenarioCatalog.length === 0) {
          setIsInitializing(false);
          setDbError(null);
          setDb(null);
          return;
        }
        setIsInitializing(true);
        setDbError(null);
        setDb(null);
        console.log('[DuckDB] Instantiating MVP bundle...');

        const worker = new Worker(mvp_worker);
        const logger = new duckdb.ConsoleLogger();
        internalDb = new duckdb.AsyncDuckDB(logger, worker);

        // Pass null explicitly — no pthread worker needed for MVP
        await internalDb.instantiate(duckdb_wasm, null);
        console.log('[DuckDB] WASM instantiated. Registering parquet files...');

        const base = window.location.origin;
        const register = (alias, path) =>
          internalDb.registerFileURL(
            alias,
            new URL(path, base).toString(),
            duckdb.DuckDBDataProtocol.HTTP,
            false
          );

        for (const scenario of scenarioCatalog) {
          const paths = scenario.paths || {};
          for (const kind of SCENARIO_FILE_KINDS) {
            if (!paths[kind]) continue;
            await register(`${scenario.id}_${kind}.parquet`, paths[kind]);
          }
        }
        for (const [artifact, path] of Object.entries({
          ...geoPaths,
          ...semanticPaths,
        })) {
          if (!path) continue;
          await register(`${artifact}.parquet`, path);
        }

        console.log('[DuckDB] Scenario and base files registered. Engine ready');
        if (!cancelled) setDb(internalDb);
      } catch (err) {
        console.error('[DuckDB] Initialization failed:', err);
        if (!cancelled) setDbError(err.message || String(err));
      } finally {
        if (!cancelled) setIsInitializing(false);
      }
    }

    initializeDuckDB();

    return () => {
      cancelled = true;
      if (internalDb) internalDb.terminate();
    };
  }, [scenarioPayload]);

  return { db, isInitializing, dbError };
}
