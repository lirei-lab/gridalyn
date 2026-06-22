"""Centralized EV Hosting Flex project configuration.

Locks the reproducibility and threshold conventions every later stage of the
``ev_hosting_flex`` pipeline inherits (decisions D-02, D-05, D-06, D-07). The
flattened module-level constants below are the contract: ``_topology.py`` and
the stage scripts import them directly.
"""

from pathlib import Path
import json

ROOT = Path(__file__).parents[3]
PROJECT_ROOT = ROOT / "projects" / "ev_hosting_flex"
PROJECT_OUTPUTS_DIR = PROJECT_ROOT / "outputs"
PROJECT_CACHE_DIR = PROJECT_OUTPUTS_DIR / "cache"
TOPOLOGY_CACHE_MANIFEST = PROJECT_CACHE_DIR / "topology_cache_manifest.json"

# ─── Load the underlying physical system configuration ──────────────────
with open(ROOT / "configs/grid/config.json") as f:
    GRID_CONFIG = json.load(f)

# ─── Phase-8 locked reproducibility + threshold conventions ─────────────
# These are flattened module-level constants (the contract for downstream
# stages). A nested PROJECT_CONFIG dict can grow later for grouping, but the
# flat names below are what every consumer imports.

POWER_FACTOR = 0.95
"""Power factor for BOTH line and transformer kW conversion (D-05, A4)."""

LINE_LOADING_LIMIT_PERCENT = 100
"""Thermal loading limit (%) above which a line is congested (D-06)."""

DTYPE = "float64"
"""Float dtype used throughout every numeric path (D-07)."""

SEED = 42
"""Single pinned seed. Consume via ``np.random.default_rng(SEED)`` — NEVER the
global ``np.random.seed`` (D-07)."""

ROUND_DECIMALS = 6
"""Pre-write rounding so float noise < 1e-6 never reaches the Phase-12
regression comparator (D-07)."""

FEEDER_ID = None
"""Feeder-selection override (D-02). ``None`` → deterministic
max-downstream-load selection with a ``(-load_kw, idx)`` tie-break."""
