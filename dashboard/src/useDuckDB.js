import { useState, useEffect } from 'react';
import * as duckdb from '@duckdb/duckdb-wasm';
import duckdb_wasm from '@duckdb/duckdb-wasm/dist/duckdb-mvp.wasm?url';
import mvp_worker from '@duckdb/duckdb-wasm/dist/duckdb-browser-mvp.worker.js?url';
import { buildScenarioCatalog } from './scenarios';

// Force MVP bundle — does NOT require SharedArrayBuffer
// (EH/pthread bundles can hang on non-HTTPS origins like Tailscale HTTP)
export function useDuckDB(scenarios = buildScenarioCatalog()) {
  const [db, setDb] = useState(null);
  const [isInitializing, setIsInitializing] = useState(true);
  const [dbError, setDbError] = useState(null);
  const scenarioPayload = JSON.stringify(
    scenarios.map(scenario => ({
      id: scenario.id,
      paths: scenario.paths,
    }))
  );

  useEffect(() => {
    let internalDb = null;
    let cancelled = false;

    async function initializeDuckDB() {
      try {
        const scenarioCatalog = JSON.parse(scenarioPayload);
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
        for (const scenario of scenarioCatalog) {
          const id = scenario.id;
          const paths = scenario.paths || {};
          await internalDb.registerFileURL(
            `${id}_nodes.parquet`,
            new URL(paths.nodes, base).toString(),
            duckdb.DuckDBDataProtocol.HTTP,
            false
          );
          await internalDb.registerFileURL(
            `${id}_lines.parquet`,
            new URL(paths.lines, base).toString(),
            duckdb.DuckDBDataProtocol.HTTP,
            false
          );
          await internalDb.registerFileURL(
            `${id}_power.parquet`,
            new URL(paths.power, base).toString(),
            duckdb.DuckDBDataProtocol.HTTP,
            false
          );
          await internalDb.registerFileURL(
            `${id}_transformers.parquet`,
            new URL(paths.transformers, base).toString(),
            duckdb.DuckDBDataProtocol.HTTP,
            false
          );
        }

        console.log('[DuckDB] Scenario files registered. Engine ready');
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
