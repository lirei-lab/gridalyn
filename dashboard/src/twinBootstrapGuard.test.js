import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

/**
 * The dashboard must discover the twin, not know it by heart.
 *
 * These are guards, not a one-time cleanup. The paths came back once already:
 * every artifact the dashboard reads is named by the twin's catalog, so a
 * literal here is a claim about the twin's layout that nothing verifies and
 * that silently rots when the twin changes.
 */

const SRC = dirname(fileURLToPath(import.meta.url));
const BOOTSTRAP = 'twinSource.js';

function sourceFiles() {
  return readdirSync(SRC)
    .filter(name => /\.(js|jsx)$/.test(name))
    .filter(name => !name.endsWith('.test.js'))
    .filter(name => name !== BOOTSTRAP);
}

function read(name) {
  return readFileSync(join(SRC, name), 'utf8');
}

test('only the bootstrap module names an instance path', () => {
  const offenders = sourceFiles().filter(name => read(name).includes('instances/'));
  assert.deepEqual(
    offenders,
    [],
    `these modules hardcode an instance path instead of deriving it from ` +
      `twinPath()/the catalog: ${offenders.join(', ')}`
  );
});

test('the bootstrap names exactly one instance root', () => {
  const matches = read(BOOTSTRAP).match(/'\/instances\/[^']*'/g) || [];
  assert.equal(
    matches.length,
    1,
    `${BOOTSTRAP} should carry a single TWIN_ROOT, found: ${matches.join(', ')}`
  );
});

test('no module hardcodes a scenario id', () => {
  // `S<digits>` in quotes. Scenario ids come from the catalog; a literal one
  // is a study leaking into a twin-generic view.
  const offenders = sourceFiles().filter(name => /['"]S\d+['"]/.test(read(name)));
  assert.deepEqual(offenders, [], `hardcoded scenario ids in: ${offenders.join(', ')}`);
});

test('no module builds an absolute twin artifact path', () => {
  // Absolute, because that is what bypasses the bootstrap: a leading slash
  // means the module asserts the twin's on-disk layout for itself. A relative
  // fragment handed to `twinPath()` still resolves through TWIN_ROOT, so the
  // one remaining convention shim -- `conventionalPaths`, for a pre-catalog
  // twin whose manifests declare no paths -- is correctly not flagged here.
  // DuckDB aliases like `S0_nodes.parquet` are handles the app chooses, not
  // paths, and are likewise not the target.
  const offenders = sourceFiles().filter(name => {
    const literals = read(name).match(/['"`][^'"`]*\.parquet[^'"`]*['"`]/g) || [];
    return literals.some(literal => /['"`]\//.test(literal));
  });
  assert.deepEqual(
    offenders,
    [],
    `these modules assert an absolute artifact path rather than resolving it ` +
      `through the catalog or twinPath(): ${offenders.join(', ')}`
  );
});
