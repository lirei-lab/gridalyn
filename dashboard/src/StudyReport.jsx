import { partitionSummary, summaryRows } from './projectCatalog';

/**
 * One governed report, rendered by what the study DECLARED matters.
 *
 * Every summary value used to get an identical tile at identical size --
 * about thirty of them on the widest shipped study -- so the objective value
 * and the bus count read as equals and the whole thing read as a wall.
 *
 * Nothing here is study-specific, and nothing here decides what is important:
 * `declared` comes from `spec.experiments[].metrics` and `governed` from the
 * baseline pins. A study that declares neither renders exactly as before, only
 * denser -- which is the honest fallback, because nothing said otherwise.
 */
export default function StudyReport({ artifact, report, error, declared, governed }) {
  // The SUMMARY, not the report: summaryRows enumerates the mapping it is
  // handed, and handing it the whole report lists report_id and
  // schema_version instead of the study's numbers.
  const rows = summaryRows(report?.summary);
  const { headline, supporting } = partitionSummary(rows, { declared, governed });
  const invalid = report?.validation?.valid === false;

  return (
    <section className="study-report">
      <div className="study-report__head">
        <h2>{artifact.report_id || artifact.relative}</h2>
        <span className={`study-report__verdict${invalid ? ' is-invalid' : ''}`}>
          {invalid ? 'validation failed' : 'validated'}
        </span>
      </div>
      <p className="study-report__source">
        {artifact.source_domain && `${artifact.source_domain} · `}
        <a href={artifact.path}>{artifact.relative}</a>
      </p>

      {error && <p className="study-report__error">⚠ {error}</p>}

      {headline.length > 0 && (
        <div className="study-report__headline">
          {headline.map(row => (
            <div key={row.key} className="study-metric">
              <span className="study-metric__label">{row.label}</span>
              {/* summaryRows has already formatted the value; formatting it
                  again would re-round what it rendered. */}
              <strong className="study-metric__value">{row.value}</strong>
              <span className="study-metric__tags">
                {/* Two different statements, kept apart: what the study set
                    out to measure, and what a re-run is checked against. */}
                {row.declared && (
                  <span className="study-tag" title="declared by this study as a result it measures">
                    declared
                  </span>
                )}
                {row.governed && (
                  <span className="study-tag study-tag--governed" title="pinned in results_baseline.json; a re-run is checked against it">
                    governed
                  </span>
                )}
              </span>
            </div>
          ))}
        </div>
      )}

      {supporting.length > 0 && (
        <dl className="study-report__supporting">
          {supporting.map(row => (
            <div key={row.key}>
              <dt>{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
      )}

      {rows.length === 0 && !error && (
        <p className="study-report__empty">This report carries no summary.</p>
      )}
    </section>
  );
}
