import { useEffect, useState } from 'react';

/**
 * The floating panel over the map: scrollable, collapsible, width-bounded.
 *
 * It was none of those. The panel was an absolutely-positioned div with no
 * maxHeight and no overflow rule, so it grew to whatever its content needed
 * and the viewport simply cut it off -- on a 1391px-tall screen the ontology
 * legend, the heatmap selector, the layer toggles and the study panels were
 * all below the fold and reachable by no means at all. Adding one row per
 * declared ontology class is what pushed it over, so the regression came from
 * the panel that most needs to be read.
 *
 * Three rules, and the third is the one that is easy to miss:
 *
 *  - It scrolls. `maxHeight` is viewport-relative rather than fixed, so the
 *    same panel works on a laptop and on the 1391px screen this was reported
 *    from.
 *  - It collapses, because the MAP is the subject of this view and the panel
 *    covered half of it with no way to move it aside.
 *  - Its width is bounded. The model identity is a single 70-character
 *    unbreakable token, and a token that cannot wrap sets the width of the box
 *    around it: the overlay was ~1100px on a wide screen because of one line
 *    of provenance nobody sized for.
 */

const STORAGE_KEY = 'gridalyn.overlay.collapsed';

/** Read the remembered state, tolerating a browser that refuses storage. */
function readCollapsed() {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === 'true';
  } catch {
    // Private windows and blocked site data throw on access, not just on
    // write. A panel that cannot remember its state must still render.
    return false;
  }
}

export default function OverlayPanel({ title, children }) {
  const [collapsed, setCollapsed] = useState(readCollapsed);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, String(collapsed));
    } catch {
      // Not remembering is a smaller failure than not rendering.
    }
  }, [collapsed]);

  return (
    <div
      className={`twin-overlay${collapsed ? ' twin-overlay--collapsed' : ''}`}
      // The scroll container is this element, so the sticky header below stays
      // put while the content moves under it.
      style={{ maxHeight: collapsed ? undefined : 'calc(100vh - 40px)' }}
    >
      <div className="twin-overlay__bar">
        <span className="twin-overlay__title">{title}</span>
        <button
          type="button"
          className="twin-overlay__toggle"
          onClick={() => setCollapsed(value => !value)}
          aria-expanded={!collapsed}
          title={collapsed ? 'Show the twin panel' : 'Collapse the twin panel'}
        >
          {collapsed ? '▸' : '▾'}
        </button>
      </div>
      {!collapsed && <div className="twin-overlay__body">{children}</div>}
    </div>
  );
}
