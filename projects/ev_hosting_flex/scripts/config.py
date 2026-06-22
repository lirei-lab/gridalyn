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
# Project-local mirror of ``configs/grid/config.json`` that opts into
# ``lines.sizing.mode = "load_aware"`` (08.1-02). Keeping a SEPARATE file leaves
# the shared ``configs/grid/config.json`` byte-identical so flexibility_cls, the
# tutorials, and test_line_sizing_diagnostic stay green (LINESIZE-01).
GRID_CONFIG_PATH = PROJECT_ROOT / "inputs" / "synthetic_network_config.json"
with open(GRID_CONFIG_PATH) as f:
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

# ─── Phase-9 annual-profile + EV + sweep + calendar knobs ───────────────
# APPENDED below the locked Phase-8 contract (do NOT edit the constants above).
# These pin the Trois-Rivieres cold-climate residential reproducibility
# contract for the deterministic 8760h winter-peaked base building load and the
# evening-window EV charging unit profile (D-03/D-04/D-05/D-07/D-08, Open-Q3).

WINTER_PEAK_FACTOR = 1.6
"""Seasonal winter-peak multiplier on the base envelope (D-03). Cold-climate
Trois-Rivieres electric-heating winters drive the heaviest residential load; the
envelope peaks here in Jan/Dec and troughs at ``SUMMER_TROUGH_FACTOR`` in
summer."""

SUMMER_TROUGH_FACTOR = 0.7
"""Seasonal summer floor of the base envelope (D-03). The seasonal multiplier
interpolates between this trough (Jul) and ``WINTER_PEAK_FACTOR`` (Jan/Dec) so
winter > summer at every hour-of-day."""

DAILY_PATTERN = (
    0.55, 0.50, 0.48, 0.47, 0.48, 0.55,  # 00:00-05:00 overnight base
    0.70, 0.85, 0.80, 0.72, 0.68, 0.66,  # 06:00-11:00 morning ramp
    0.65, 0.64, 0.65, 0.70, 0.82, 1.00,  # 12:00-17:00 building toward peak
    1.05, 1.00, 0.92, 0.80, 0.68, 0.60,  # 18:00-23:00 evening heating peak
)
"""24-hour-of-day shape coefficients (D-03), index = ``hour_of_year % 24``. The
evening heating peak (~17:00-21:00) coincides with the EV ``CHARGING_WINDOW`` so
EV coincidence stresses the same hours as the base peak (the firm-limit driver).
"""

WEEKLY_PATTERN = (
    1.00, 0.99, 0.99, 0.99, 1.00, 1.04, 1.05,
)
"""7-day-of-week shape coefficients (D-03), Mon=0 .. Sun=6, indexed by weekday
derived from ``CALENDAR_START_WEEKDAY``. Weekends carry slightly higher
residential occupancy load."""

EV_UNIT_KW = 7.2
"""Per-EV charging power in kW (D-05). A typical residential 240 V / 32 A AC
Level-2 charger draws ~7.2 kW at full power."""

DIVERSITY_FACTOR = 0.6
"""Simultaneous-draw fraction at the evening peak (D-05, Pitfall 5). Not all EVs
charge at once; 0.6 is the coincident fraction applied to the per-EV unit draw.
Deliberately NOT 1.0 (over-pessimistic) and NOT negligible."""

CHARGING_WINDOW = (17, 22)
"""``(start_hour, end_hour)`` evening EV charging window (D-04), end-exclusive.
Chosen to overlap the evening winter heating peak in ``DAILY_PATTERN`` so EV
coincidence binds the firm hosting limit."""

EV_SWEEP = (0, 20, 40, 60, 80, 100, 120, 140, 160, 180, 200)
"""Ascending total-feeder EV counts to sweep (D-07/D-08), integer step 20 from 0
up past the expected firm crossing for a ~260 kW / 27-bus feeder. The swept
variable is the TOTAL EV count on the feeder (the headline units)."""

CALENDAR_HOURS = 8760
"""Non-leap hour-of-year count (Open-Q3). 365 days x 24 h; the pinned time index
for every annual profile and the Phase-12 hour x line congestion heatmap."""

CALENDAR_START_WEEKDAY = 0
"""Weekday of hour-of-year 0 (Open-Q3), Mon=0 .. Sun=6. Pinned to Monday so the
season->hour mapping is deterministic: day-of-year = ``hour_of_year // 24``,
weekday = ``(day_of_year + CALENDAR_START_WEEKDAY) % 7``; winter (Jan/Dec) sits
at the low/high day-of-year ends, summer (Jul) near day 180."""
