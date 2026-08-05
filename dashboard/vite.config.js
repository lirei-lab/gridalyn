import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

function digitalTwinStaticPlugin() {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
  const roots = {
    '/instances/default/digital_twin': path.join(root, 'instances', 'default', 'digital_twin'),
    '/projects': path.join(root, 'projects'),
  }

  return {
    name: 'gridalyn-data-static',
    configureServer(server) {
      for (const [mountPath, dataRoot] of Object.entries(roots)) {
        server.middlewares.use(mountPath, (req, res, next) => {
          const rawUrl = decodeURIComponent((req.url || '').split('?')[0])
          const filePath = path.normalize(path.join(dataRoot, rawUrl))
          if (filePath !== dataRoot && !filePath.startsWith(`${dataRoot}${path.sep}`)) {
            res.statusCode = 403
            res.end('Forbidden')
            return
          }
          fs.stat(filePath, (err, stat) => {
            if (err || !stat.isFile()) {
                // 404, not next(). Falling through hands the request to Vite's
                // SPA fallback, which answers 200 with index.html -- so every
                // `if (!res.ok) return null` guard in the loaders goes dead and
                // `res.json()` throws on "<!doctype html>" instead. One missing
                // file then rejects a whole Promise.all and the catalog renders
                // empty with nothing surfaced to the user.
                res.statusCode = 404
                res.end('Not found')
              return
            }
            if (filePath.endsWith('.parquet')) res.setHeader('Content-Type', 'application/octet-stream')
            if (filePath.endsWith('.json')) res.setHeader('Content-Type', 'application/json')
            fs.createReadStream(filePath).pipe(res)
          })
        })
      }
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), digitalTwinStaticPlugin()],
  server: {
    host: '0.0.0.0',
    fs: {
      allow: ['..'],
    },
    headers: {
      'Cross-Origin-Opener-Policy': 'same-origin',
      'Cross-Origin-Embedder-Policy': 'require-corp',
    },
    // Suppress "Failed to load source map" warnings from node_modules (e.g. duckdb-wasm)
    sourcemapIgnoreList: (sourcePath) => sourcePath.includes('node_modules'),
  },
  // DuckDB-WASM must NOT be pre-bundled — esbuild breaks WASM worker imports
  optimizeDeps: {
    exclude: ['@duckdb/duckdb-wasm'],
  },
  build: {
    chunkSizeWarningLimit: 2000,
    rollupOptions: {
      onwarn(warning, warn) {
        // Suppress missing .map file warnings from DuckDB npm package
        if (warning.code === 'SOURCEMAP_ERROR') return;
        warn(warning);
      },
    },
  },
})
