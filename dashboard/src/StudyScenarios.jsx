/**
 * A study's scenarios, as the study itself declares them.
 *
 * The dashboard used to know exactly one scenario shape: the twin's four
 * artifact kinds, at a path the client synthesized from the twin's on-disk
 * naming convention. A study whose scenarios are partitioned the other way --
 * one artifact holding every scenario, discriminated by a column, rather than
 * one artifact per scenario and kind -- could not be shown at all.
 *
 * Nothing here names a kind. The kinds are whatever the catalog carries for
 * this source, and each arrives with the partitioning it must be read under,
 * because that changes what the path means: file-partitioned holds this
 * scenario alone, column-partitioned holds all of them.
 */
export default function StudyScenarios({ scenarios }) {
  if (!scenarios || scenarios.length === 0) return null;

  return (
    <section
      style={{ marginTop: '24px', borderTop: '1px solid #333', paddingTop: '16px' }}
    >
      <h2 style={{ margin: '0 0 4px', fontSize: '1.05rem' }}>
        Scenarios{' '}
        <span style={{ color: '#777', fontWeight: 'normal' }}>· {scenarios.length}</span>
      </h2>
      <p
        style={{
          color: '#777',
          fontSize: '0.75rem',
          margin: '0 0 12px',
          maxWidth: '80ch',
        }}
      >
        Enumerated from the indexer this study declares in{' '}
        <code style={{ color: '#4aa' }}>spec.scenarios</code>. Each kind carries how it
        must be read: <strong>file</strong> means the path holds this scenario alone,{' '}
        <strong>column</strong> means it holds every scenario and a column selects.
      </p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {scenarios.map(scenario => (
          <div key={scenario.id} style={{ fontSize: '0.85rem' }}>
            <span style={{ color: '#9de7ff', fontWeight: 'bold' }}>{scenario.id}</span>
            <span style={{ color: '#aaa' }}> — {scenario.label}</span>
            <div
              style={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: '10px',
                marginTop: '3px',
              }}
            >
              {scenario.kinds.map(entry => (
                <a
                  key={entry.kind}
                  href={entry.path}
                  style={{ color: '#4aa', fontSize: '0.75rem', textDecoration: 'none' }}
                  title={`${entry.partitioning}-partitioned${
                    entry.idColumn ? ` on ${entry.idColumn}` : ''
                  }`}
                >
                  {entry.kind}
                  <span style={{ color: '#666' }}> ({entry.partitioning})</span>
                </a>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
