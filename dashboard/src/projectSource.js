// Which governed project the dashboard reads.
//
// The artifact paths used to be spelled out in each module, so the dashboard
// was wired to one study by name and could not be pointed at another without
// editing source. The SDK writers were never the problem — they take
// `project_id` — the dashboard simply hardcoded the answer.
//
// Configure with `VITE_GRIDALYN_PROJECT` at build time, or call the path
// helpers with an explicit `project` argument at runtime.

export const FALLBACK_PROJECT = 'ev_hosting_flex';

function envValue(env) {
  // `import.meta.env` is absent under plain node (the unit tests), so this
  // resolves defensively rather than throwing there.
  if (env && typeof env === 'object' && env.VITE_GRIDALYN_PROJECT) {
    return String(env.VITE_GRIDALYN_PROJECT);
  }
  return null;
}

/**
 * Resolve the project whose artifacts the dashboard should read.
 *
 * @param {object} [env] - environment mapping; defaults to Vite's import.meta.env.
 * @returns {string} project directory name under `projects/`.
 */
export function operatingProject(env = undefined) {
  const explicit = envValue(env);
  if (explicit) return explicit;
  try {
    const viteEnv = envValue(import.meta.env);
    if (viteEnv) return viteEnv;
  } catch {
    // no import.meta in this runtime — fall through to the default
  }
  return FALLBACK_PROJECT;
}

/**
 * Build a path under a project's outputs directory.
 *
 * @param {string[]} segments - path segments below `outputs/`.
 * @param {string} [project] - project name; defaults to {@link operatingProject}.
 * @returns {string} absolute served path.
 */
export function projectOutputsPath(segments, project = undefined) {
  const name = project || operatingProject();
  return ['', 'projects', name, 'outputs', ...segments].join('/');
}

/** Path to the operations catalog the operations panel reads. */
export function operationsCatalogPath(project = undefined) {
  return projectOutputsPath(['operations', 'operations_catalog.json'], project);
}

/** Path to the operational KPI report the clearing scorecard reads. */
export function operationalKpiReportPath(project = undefined) {
  return projectOutputsPath(
    ['reports', 'operational_kpi_report.json'],
    project,
  );
}
