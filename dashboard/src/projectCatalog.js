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
