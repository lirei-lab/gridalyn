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

test('no module names a shipped study', () => {
  // Read from `projects/` rather than from a list kept here, so a study added
  // to the repo is covered without editing this test. The dashboard reads a
  // study's artifacts as a SOURCE described by the catalog; naming one is what
  // made a single study a first-class mode and required a bespoke component.
  const projectsDir = join(SRC, '..', '..', 'projects');
  const studies = readdirSync(projectsDir, { withFileTypes: true })
    .filter(entry => entry.isDirectory() && !entry.name.startsWith('_'))
    .map(entry => entry.name);
  assert.ok(studies.length >= 6, `expected the shipped studies, found ${studies.length}`);

  const offenders = [];
  for (const name of sourceFiles()) {
    const source = read(name);
    for (const study of studies) {
      if (source.includes(study)) offenders.push(`${name} -> ${study}`);
    }
  }
  assert.deepEqual(
    offenders,
    [],
    `these modules name a study instead of reading it from the catalog: ${offenders.join(', ')}`
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

/** The catalog artifact this repo tracks -- where the two languages must agree. */
function shippedCatalog() {
  return JSON.parse(
    readFileSync(
      join(SRC, '..', '..', 'instances', 'default', 'digital_twin', 'dashboard', 'catalog.json'),
      'utf8'
    )
  );
}

test('the shipped catalog states whether this instance is a shadow', () => {
  // Absent would make "no measured data" and "this catalog is too old to say"
  // the same observation, which is the distinction the block exists for. It
  // must survive a regeneration, whatever the instance happens to hold.
  const observation = shippedCatalog().observation;
  assert.ok(observation, 'the shipped catalog declares no observation block');
  assert.ok(
    observation.provenance_values.includes(observation.provenance),
    `provenance ${observation.provenance} is outside the declared vocabulary ` +
      `(${observation.provenance_values.join(', ')})`
  );
  assert.equal(
    typeof observation.measured.available,
    'boolean',
    'measured availability must be answered, not omitted'
  );
  if (!observation.measured.available) {
    assert.ok(
      observation.measured.absent_reason,
      'an instance with no measured data must say why, not go quiet'
    );
  }
});

test('every shipped scenario states where its numbers came from', () => {
  const catalog = shippedCatalog();
  const values = catalog.observation.provenance_values;
  for (const scenario of catalog.scenarios) {
    assert.ok(
      values.includes(scenario.provenance),
      `scenario ${scenario.scenario_id} declares provenance ` +
        `${scenario.provenance}, outside ${values.join(', ')}`
    );
  }
});

test('the client can read the catalog this repo actually ships', async () => {
  // Cross-language drift is invisible to either side's own tests: the SDK
  // bumped the catalog to 1.2 while this client still declared 1.0/1.1, so the
  // dashboard warned that the repo's own catalog was unreadable. Reading the
  // tracked artifact is what makes the two sides fail together.
  const { SUPPORTED_SCHEMA_VERSIONS } = await import('./twinSource.js');
  const catalogPath = join(
    SRC,
    '..',
    '..',
    'instances',
    'default',
    'digital_twin',
    'dashboard',
    'catalog.json'
  );
  const catalog = JSON.parse(readFileSync(catalogPath, 'utf8'));
  assert.ok(
    SUPPORTED_SCHEMA_VERSIONS.includes(catalog.schema_version),
    `the shipped catalog is schema ${catalog.schema_version}, which this client ` +
      `does not declare support for (${SUPPORTED_SCHEMA_VERSIONS.join(', ')})`
  );
});

test('no module names an ontology class', () => {
  // Same rule as scenario ids and studies, for the same reason: the classes
  // come from the catalog, and a literal one here is the coupling the derived
  // layer registry exists to remove -- a twin whose profile names a class this
  // repo has never seen must still reach the map.
  const catalogPath = join(
    SRC,
    '..',
    '..',
    'instances',
    'default',
    'digital_twin',
    'dashboard',
    'catalog.json'
  );
  const catalog = JSON.parse(readFileSync(catalogPath, 'utf8'));
  const classes = [
    ...new Set((catalog.semantic?.classes || []).map(entry => entry.class)),
  ];
  assert.ok(classes.length >= 4, `expected the twin's classes, found ${classes.length}`);

  // Quoted-literal form, the same shape the scenario-id guard uses: what makes
  // a class name load-bearing is being compared, keyed or branched on, and all
  // three spell it as a string literal. Prose in a comment, and UI text that
  // happens to share a word, are not the target.
  const offenders = [];
  for (const name of sourceFiles()) {
    const source = read(name);
    for (const declared of classes) {
      const literal = new RegExp(
        `(['"\`])${declared.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\1`
      );
      if (literal.test(source)) offenders.push(`${name} -> ${declared}`);
    }
  }
  assert.deepEqual(
    offenders,
    [],
    `these modules name an ontology class instead of deriving it from the ` +
      `catalog: ${offenders.join(', ')}`
  );
});

test('the catalog this repo ships actually carries the ontology', () => {
  // The SDK can stop publishing `semantic` -- a regenerated catalog from a
  // twin with no semantic dir, a build that forgot the flag -- and no Python
  // test would notice, because the block is legitimately optional there. The
  // tracked artifact is where the two sides have to agree.
  const catalogPath = join(
    SRC,
    '..',
    '..',
    'instances',
    'default',
    'digital_twin',
    'dashboard',
    'catalog.json'
  );
  const catalog = JSON.parse(readFileSync(catalogPath, 'utf8'));
  const semantic = catalog.semantic;
  assert.ok(semantic, 'the shipped catalog declares no semantic block');
  assert.ok(
    semantic.classes.length > 0,
    `the shipped catalog declares no ontology class: ${semantic.classes_absent_reason}`
  );
  // Every class must be attributable: the three populations do not coincide,
  // so an entry that does not say which one it came from is unusable.
  for (const entry of semantic.classes) {
    assert.ok(
      semantic.populations.includes(entry.population),
      `class ${entry.class} claims population ${entry.population}, which the ` +
        `catalog does not declare (${semantic.populations.join(', ')})`
    );
  }
});

test('only the pre-catalog fallback names a scenario artifact kind', () => {
  // A scenario's kinds are whatever its catalog entry declares. The twin
  // partitions BY FILE (one artifact per scenario and kind) and a study may
  // partition BY COLUMN (one artifact holding every scenario); a client that
  // names either one's kinds cannot read the other. The list lived in THREE
  // places -- here, in the SDK, and in useDuckDB.js -- with nothing keeping
  // them in sync.
  //
  // scenarios.js is the one exemption, and only for `buildScenarioCatalog`:
  // the fallback runs when no catalog exists to declare anything, so the
  // naming convention is the only route left. Same exemption, same reason, as
  // LEGACY_MANIFEST_PATHS.semanticManifest.
  const kinds = ['powerflow_nodes', 'powerflow_lines', 'powerflow_power'];
  const offenders = [];
  for (const name of sourceFiles()) {
    if (name === 'scenarios.js') continue;
    const source = read(name);
    for (const kind of kinds) {
      if (source.includes(kind)) offenders.push(`${name} -> ${kind}`);
    }
  }
  assert.deepEqual(
    offenders,
    [],
    `these modules name a scenario artifact kind instead of reading the kinds ` +
      `the catalog declares: ${offenders.join(', ')}`
  );
});

test('the exemption stays confined to the fallback', () => {
  // If the convention leaks back into the live path, the exemption above stops
  // being an exemption and becomes a hole. The live path is
  // buildDashboardScenarioCatalog; the shim must be reached only from
  // buildScenarioCatalog.
  const source = read('scenarios.js');
  const live = source.slice(
    source.indexOf('export function buildDashboardScenarioCatalog'),
    source.indexOf('export function scenarioIdsFromManifest')
  );
  assert.ok(live.length > 0, 'could not locate the live catalog path');
  assert.ok(
    !live.includes('legacyConventionalPaths') && !live.includes('LEGACY_FILE_KINDS'),
    'the pre-catalog naming convention leaked into the live catalog path'
  );
});

test('map layers are created only in the registry', () => {
  // "Adding a layer touches the registry, not the app component" is the point
  // of the layer model; a `new SomethingLayer(...)` anywhere else silently
  // reintroduces a layer that cannot be listed, toggled or described.
  const offenders = sourceFiles()
    .filter(name => name !== 'mapLayers.js')
    .filter(name => /new\s+\w*Layer\s*\(/.test(read(name)));
  assert.deepEqual(
    offenders,
    [],
    `these modules instantiate a deck.gl layer outside mapLayers.js: ${offenders.join(', ')}`
  );
});

test('the app component composes rather than renders the map', () => {
  // App.jsx held the map, its six layers, its tooltip and its viewport inline.
  // The specific ceiling matters less than the direction: it was 1228 lines
  // and must not silently grow back.
  const app = read('App.jsx').split('\n').length;
  assert.ok(app < 1000, `App.jsx is ${app} lines; it was extracted down from 1228`);
});
