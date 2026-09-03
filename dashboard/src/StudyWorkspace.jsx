import {
  declaredMetrics,
  describeScenarios,
  governedMetrics,
} from './projectCatalog';
import StudyReport from './StudyReport';
import StudyScenarios from './StudyScenarios';

/**
 * The study workspace: everything the dashboard shows when the subject is a
 * study rather than the twin.
 *
 * Extracted from App.jsx, which held the twin view, this view and the map
 * wiring in one file against a guarded 1000-line ceiling. The two views share
 * only the workspace selector, which moves here and is re-exported.
 */
function WorkspaceSelector({ activeWorkspace, onChange, workspaces = [] }) {
  return (
    <div className="workspace-switcher">
      <label htmlFor="workspace-select">Workspace</label>
      <select
        id="workspace-select"
        value={activeWorkspace}
        onChange={event => onChange(event.target.value)}
      >
        {workspaces.map(workspace => (
          <option key={workspace.id} value={workspace.id}>
            {workspace.label}
            {workspace.available === false ? ' (not run)' : ''}
          </option>
        ))}
      </select>
    </div>
  );
}

/**
 * Render any governed study, from what the catalog declares about it.
 *
 * Replaces a 131-line component dedicated to one study. Nothing here knows a
 * study by name: the panel lists the reports the catalog says a project
 * declares, renders each one's `summary` as label/value rows through the
 * platform report contract, and links whatever tables the study ships. A study
 * added to `projects/` appears with no edit to this file.
 *
 * What this deliberately does NOT do is draw a study-specific chart. The old
 * panel could, because it knew that one study's CSV column names; no declared
 * column contract exists for a study's tables, so inventing charts from
 * guessed columns would rebuild the coupling this removes. Tables are linked,
 * not plotted, until a study can declare its columns.
 */
function ProjectDashboard({ workspace, reports, loading, activeWorkspace, onWorkspaceChange, workspaces }) {
  const tabularArtifacts = (workspace?.artifacts || []).filter(
    artifact => artifact.kind === 'table'
  );
  const missing = (workspace?.artifacts || []).filter(artifact => !artifact.exists);
  // Read from what the study DECLARED, not discovered. A study with no
  // scenario indexer yields none and this section does not render.
  const scenarios = describeScenarios(workspace);
  // What the study says it measures. Empty for a study that declares none, in
  // which case every value stays supporting detail rather than being promoted
  // by a guess.
  const declared = declaredMetrics(workspace);

  return (
    <div className="project-dashboard">
    <div className="project-dashboard__panel">
      <div className="project-dashboard__header">
        <div>
          <h1>{workspace?.label || activeWorkspace}</h1>
          {workspace?.description && <p>{workspace.description}</p>}
          {/* The question this study asks. Declared by all eight studies and
              read by nothing until now: numbers without their question. */}
          {workspace?.objective && (
            <p className="project-dashboard__objective">{workspace.objective}</p>
          )}
        </div>
        <WorkspaceSelector
          activeWorkspace={activeWorkspace}
          onChange={onWorkspaceChange}
          workspaces={workspaces}
        />
      </div>

      {(workspace?.experiments || []).length > 0 && (
        <section className="study-experiments">
          {workspace.experiments.map(experiment => (
            <div key={experiment.id} className="study-experiment">
              <span className="study-experiment__id">{experiment.id}</span>
              {experiment.objective && <p>{experiment.objective}</p>}
              {experiment.metrics.length > 0 && (
                <p className="study-experiment__metrics">
                  measures {experiment.metrics.join(' · ')}
                </p>
              )}
            </div>
          ))}
        </section>
      )}

      {loading && <p style={{ color: 'rgb(0,200,200)' }}>Loading declared artifacts...</p>}

      {!loading && missing.length > 0 && (
        <p style={{ color: '#ffaa33', fontSize: '0.8rem' }}>
          {/* Said, not hidden: the two heavy studies gitignore their outputs,
              so an empty panel here is expected rather than a fault. */}
          ⚠ {missing.length} declared artifact{missing.length === 1 ? '' : 's'} not on disk.
          Run this study with `gridalyn project run projects/{workspace?.id}`.
        </p>
      )}

      {!loading && reports.length === 0 && missing.length === 0 && (
        <p style={{ color: '#aaa' }}>This study declares no governed reports to show.</p>
      )}

      <StudyScenarios scenarios={scenarios} />

      {reports.map(({ artifact, report, error }) => (
        <StudyReport
          key={artifact.path}
          artifact={artifact}
          report={report}
          error={error}
          declared={declared}
          governed={governedMetrics(workspace, artifact.relative)}
        />
      ))}

      {tabularArtifacts.length > 0 && (
        <section className="study-tables">
          <h2>Tables</h2>
          {/* No declared column contract, so these are linked rather than
              plotted. Saying so beats an empty chart. */}
          <p className="study-tables__note">
            Tabular results. These carry no declared column contract, so they are
            linked rather than charted.
          </p>
          <ul>
            {tabularArtifacts.map(artifact => (
              <li key={artifact.path}>
                <a href={artifact.path}>{artifact.relative}</a>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
    </div>
  );
}
export { WorkspaceSelector };
export default ProjectDashboard;
