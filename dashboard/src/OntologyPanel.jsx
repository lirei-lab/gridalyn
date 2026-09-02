import { describeOntologyClasses } from './ontology';
import { ontologyClassColors } from './mapLayers';

/**
 * What the twin's ontology says, as classes rather than as four scalars.
 *
 * The previous rendering was `Ontology / Valid / Nodes / Edges` -- an ontology
 * reduced to a node count, from which no reader learns that this twin knows a
 * building from an EV charging asset. This panel lists the classes the catalog
 * declares, each with its count, the population it came from, and whether the
 * map can draw it; a class it cannot draw says why rather than disappearing.
 *
 * Nothing here is a list of class names. Every row, its colour and its swatch
 * come from the catalog, so a class added to the twin appears with no edit.
 */
export default function OntologyPanel({
  semantic,
  scenarioId,
  showOntology,
  onToggleOntology,
}) {
  if (!semantic) return null;
  const classes = describeOntologyClasses(semantic, scenarioId);
  const drawable = classes.filter(entry => entry.drawable);
  // Assigned over the same set the map draws, by the same function, so a
  // swatch here is the colour on the map rather than a second guess at it.
  const colors = ontologyClassColors(drawable.map(entry => entry.name));

  return (
    <div
      style={{
        marginTop: '12px',
        paddingTop: '10px',
        borderTop: '1px solid #333',
        fontSize: '0.78rem',
        color: '#d7eeee',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ color: '#9de7ff', fontWeight: 'bold' }}>
          Ontology · {semantic.profile || 'no profile'}
        </span>
        <span style={{ color: '#8a8a8a' }}>
          {semantic.valid === null ? 'unchecked' : semantic.valid ? 'valid' : 'INVALID'}
          {' · '}
          {semantic.nodeCount ?? 'n/a'} nodes / {semantic.edgeCount ?? 'n/a'} edges
        </span>
      </div>

      {classes.length === 0 && (
        <p style={{ margin: '8px 0 0 0', color: '#8a8a8a', lineHeight: 1.35 }}>
          {semantic.classesAbsentReason || 'this twin declares no ontology class'}
        </p>
      )}

      {drawable.length > 0 && (
        <label
          style={{
            display: 'flex',
            alignItems: 'center',
            cursor: 'pointer',
            margin: '10px 0 4px 0',
          }}
        >
          <input
            type="checkbox"
            checked={showOntology}
            onChange={onToggleOntology}
            style={{ marginRight: '8px', cursor: 'pointer' }}
          />
          Draw entities by ontology class
        </label>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: '3px', marginTop: '6px' }}>
        {classes.map(entry => {
          const [red, green, blue] = colors.get(entry.name) || [0, 0, 0];
          return (
            <div
              key={`${entry.population}:${entry.artifact}:${entry.name}`}
              style={{ display: 'flex', alignItems: 'center', gap: '7px' }}
              title={
                entry.undrawableReason
                  ? `${entry.population} · ${entry.undrawableReason}`
                  : `${entry.population} · ${entry.artifact}`
              }
            >
              <span
                style={{
                  width: '9px',
                  height: '9px',
                  borderRadius: '50%',
                  flexShrink: 0,
                  background: entry.drawable
                    ? `rgb(${red},${green},${blue})`
                    : 'transparent',
                  border: entry.drawable ? 'none' : '1px solid #555',
                }}
              />
              <span style={{ color: entry.drawable ? '#e6e6e6' : '#8a8a8a' }}>
                {entry.name}
              </span>
              {/* The three populations do not coincide -- the same class name
                  can appear twice with different counts, because they count
                  different things. Naming the artifact inline is what makes a
                  repeated class name legible rather than look like a bug. */}
              <span style={{ color: '#6f6f6f', fontSize: '0.68rem' }}>
                {entry.artifact}
              </span>
              <span style={{ marginLeft: 'auto', color: '#8a8a8a' }}>{entry.count}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
