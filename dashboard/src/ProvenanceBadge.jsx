/**
 * What the values on screen ARE: solved, or measured.
 *
 * `gridalyn.twin` is a canonical digital MODEL; a deployment becomes a digital
 * SHADOW when its operator feeds it their own measured data, and
 * `NetworkObservation.provenance` is the required field that separates the
 * two inside the contract. Outside it, nothing said so: a number from a solved
 * scenario and a number ingested from a meter reached this screen looking
 * identical.
 *
 * This states it. It renders whatever provenance the catalog declared, with no
 * list of known values here -- an instance whose twin declares a provenance
 * this file has never seen still gets labelled, and gets labelled with the
 * twin's word for it.
 */

/**
 * Colour a provenance without knowing the vocabulary.
 *
 * Measured is the one worth distinguishing at a glance -- it is the claim that
 * these numbers came from the physical system. Everything else, including a
 * value this client has not seen before, reads as "stated, not verified".
 */
function tone(provenance) {
  if (provenance === 'measured') return { fg: '#7dffb0', bg: 'rgba(40,140,80,0.22)' };
  if (provenance === 'simulated') return { fg: '#9de7ff', bg: 'rgba(40,90,140,0.22)' };
  return { fg: '#d0d0d0', bg: 'rgba(120,120,120,0.22)' };
}

export default function ProvenanceBadge({ provenance, title = null }) {
  // Null is not "simulated". A catalog too old to declare a provenance has not
  // told us these values are solved, and asserting it would be inventing the
  // statement this component exists to carry.
  if (!provenance) return null;
  const { fg, bg } = tone(provenance);
  return (
    <span
      title={title || `these values are ${provenance}`}
      style={{
        display: 'inline-block',
        padding: '1px 7px',
        borderRadius: '9px',
        background: bg,
        color: fg,
        border: `1px solid ${fg}44`,
        fontSize: '0.68rem',
        letterSpacing: '0.05em',
        textTransform: 'uppercase',
        whiteSpace: 'nowrap',
      }}
    >
      {provenance}
    </span>
  );
}
