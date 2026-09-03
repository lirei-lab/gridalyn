/**
 * Reading a study's artifacts from what the twin catalog declares.
 *
 * The dashboard used to carry a component dedicated to one study, coded to
 * that study's four artifact names and to the column names inside them. The
 * study name was never the hard part -- the SHAPE was, which is why making the
 * name configurable did not remove the coupling.
 *
 * The shape that replaces it is the platform report contract: every governed
 * report carries report_id, summary, artifacts and validation, so a panel that
 * renders those renders any study's reports with no study-specific code. The
 * catalog says which artifacts a study declares and which of them are governed
 * reports; nothing here knows a study by name.
 */

export const KIND_GOVERNED_REPORT = 'governed_report';
export const KIND_TABLE = 'table';

/**
 * Workspaces the dashboard can show, derived rather than declared.
 *
 * The twin comes first because it is the subject; studies follow as sources it
 * draws on. A study whose declared artifacts are all absent -- the two heavy
 * studies gitignore their outputs -- is still listed, flagged `available:
 * false`, so a viewer can say why it is empty instead of silently omitting it.
 */
export function deriveWorkspaces(catalogProjects = []) {
  return [
    { id: 'digital_twin', label: 'Digital Twin', kind: 'digital_twin', available: true },
    ...catalogProjects.map(project => ({
      id: project.project_id,
      label: project.label || project.project_id,
      description: project.description || '',
      kind: 'project',
      available: (project.artifacts || []).some(artifact => artifact.exists),
      artifacts: project.artifacts || [],
      // What the study says it is FOR, and what it says it measures. Read from
      // the catalog so presentation follows declaration rather than per-study
      // code -- the coupling this whole view exists to avoid.
      objective: project.objective || '',
      experiments: project.experiments || [],
      governed_metrics: project.governed_metrics || [],
      // A study's scenarios, in the same shape the twin's arrive in: an id, a
      // label, `paths` keyed by the kinds THIS source declares, and the
      // partitioning each kind must be read with. Empty for a study that
      // declares no scenario indexer, which is most of them.
      scenarios: project.scenarios || [],
    })),
  ];
}

export function readProjects(catalog) {
  return Array.isArray(catalog?.projects) ? catalog.projects : [];
}

export function governedReports(workspace) {
  return (workspace?.artifacts || []).filter(
    artifact => artifact.kind === KIND_GOVERNED_REPORT && artifact.exists
  );
}

/**
 * Describe a study's scenarios for display, without assuming any kind.
 *
 * The kinds differ per source on purpose -- the twin's describe a solved power
 * flow, a study's describe whatever that study produced -- so this reports what
 * each scenario declares rather than looking for a set it expects.
 * `partitioning` travels with each kind because it changes how the artifact
 * must be READ: a file-partitioned path holds this scenario alone, a
 * column-partitioned one holds every scenario and a column selects.
 */
export function describeScenarios(workspace) {
  return (workspace?.scenarios || []).map(scenario => ({
    id: scenario.scenario_id,
    label: scenario.label || scenario.scenario_id,
    kinds: Object.entries(scenario.paths || {}).map(([kind, path]) => ({
      kind,
      path,
      partitioning: scenario.partitioning?.[kind]?.partitioning || null,
      idColumn: scenario.partitioning?.[kind]?.id_column || null,
    })),
  }));
}

/**
 * Split a study's summary into what it CLAIMS and what merely supports it.
 *
 * Every value used to get an identical tile at identical size, so a headline
 * result and a bus count read the same and ~30 of them read as a wall. The
 * hierarchy was declared all along and ignored: `spec.experiments[].metrics`
 * is the study's own statement of which numbers are the result, and a baseline
 * pin is what a re-run is checked against.
 *
 * The two are kept apart because they are different statements and, in the
 * shipped studies, they genuinely disagree: one study declares three metrics
 * and pins four other values. A number that is both declared and governed is
 * the strongest claim the contract can make; merging them would lose that.
 *
 * A study that declares no metrics gets everything as supporting detail, which
 * is honest: nothing said otherwise, so nothing is promoted.
 */
export function partitionSummary(rows, { declared = [], governed = [] } = {}) {
  const wanted = new Set(declared);
  const pinned = new Set(governed);
  const headline = [];
  const supporting = [];
  for (const row of rows) {
    const entry = {
      ...row,
      declared: wanted.has(row.key),
      governed: pinned.has(row.key),
    };
    (entry.declared || entry.governed ? headline : supporting).push(entry);
  }
  // Declared first, then governed-only: the study's stated measures lead, and
  // what the baseline additionally guards follows.
  headline.sort((a, b) => Number(b.declared) - Number(a.declared));
  return { headline, supporting };
}

/**
 * The metric keys a study declares, across every experiment it declares.
 */
export function declaredMetrics(workspace) {
  return [
    ...new Set(
      (workspace?.experiments || []).flatMap(experiment => experiment.metrics || [])
    ),
  ];
}

/**
 * The summary keys a study's baseline pins, for one report.
 *
 * Scoped by report because two reports of one study can carry the same key
 * name and only one of them may be pinned.
 */
export function governedMetrics(workspace, relative) {
  return [
    ...new Set(
      (workspace?.governed_metrics || [])
        .filter(pin => !relative || pin.source === relative)
        .map(pin => pin.key)
    ),
  ];
}

export function tables(workspace) {
  return (workspace?.artifacts || []).filter(
    artifact => artifact.kind === KIND_TABLE && artifact.exists
  );
}

/**
 * Render a governed report's summary as ordered label/value rows.
 *
 * Values are formatted by their own type rather than by a per-study mapping:
 * that mapping is exactly what tied the old panel to one study's columns.
 * Nested values are rendered as JSON rather than dropped, so a summary key is
 * never silently invisible.
 */
export function summaryRows(summary = {}) {
  return Object.entries(summary || {})
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, value]) => ({
      key,
      label: key.replace(/_/g, ' '),
      value: formatSummaryValue(value),
    }));
}

export function formatSummaryValue(value) {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return String(value);
    return Number.isInteger(value) ? String(value) : value.toFixed(4);
  }
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
}

/**
 * Fetch every governed report a workspace declares.
 *
 * A report that fails to load is reported in place rather than dropped: an
 * artifact the catalog declares and the viewer cannot read is a fact worth
 * showing, and silently shortening the list hides it.
 */
export async function loadProjectReports(workspace, fetchImpl = fetch) {
  const declared = governedReports(workspace);
  return Promise.all(
    declared.map(async artifact => {
      try {
        const response = await fetchImpl(artifact.path);
        if (!response.ok) {
          return { artifact, report: null, error: `HTTP ${response.status}` };
        }
        return { artifact, report: await response.json(), error: null };
      } catch (error) {
        return { artifact, report: null, error: error.message || String(error) };
      }
    })
  );
}
