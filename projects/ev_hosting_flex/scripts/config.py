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

WINTER_PEAK_FACTOR = 1.2
"""Seasonal winter-peak multiplier on the base envelope (D-03). Cold-climate
Trois-Rivieres electric-heating winters drive the heaviest residential load; the
envelope peaks here in Jan/Dec and troughs at ``SUMMER_TROUGH_FACTOR`` in
summer.

Recalibrated 10-03 per CALIBRATION.md "Recommended values": per-dwelling winter
peak 10-15 kW. At 1.2 the diversified per-home winter peak
(10 kW nameplate x ``annual_peak_base_factor()`` ~= 1.323) lands at ~13.2 kW,
mid-band (the prior 1.6 yielded ~17.6 kW, the verified high-end over-statement).
This factor ALSO re-sizes the feeder transformer + interior lines via
``annual_peak_base_factor()`` -> the firm denominator, so the topology cache must
be regenerated for the new value to take effect."""

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
Level-2 charger draws ~7.2 kW at full power. Kept at the L2 nameplate per
CALIBRATION.md (the coincident draw is set via ``DIVERSITY_FACTOR``, not by
lowering the nameplate)."""

DIVERSITY_FACTOR = 0.35
"""Simultaneous-draw fraction at the evening peak (D-05, Pitfall 5). Not all EVs
charge at once; this is the coincident fraction applied to the per-EV unit draw.

Recalibrated 10-03 per CALIBRATION.md "Recommended values": EV coincident power
``EV_UNIT_KW x DIVERSITY_FACTOR`` toward ~2-3 kW. At 0.35 the coincident draw is
7.2 x 0.35 = 2.52 kW, mid-band (the prior 0.6 yielded 4.32 kW, the verified
high-end). Canadian diversified is ~1.4 kW on large feeders, raised here for a
small/cold 26-dwelling feeder. Deliberately NOT 1.0 (over-pessimistic) and NOT
negligible."""

CHARGING_WINDOW = (17, 20)
"""``(start_hour, end_hour)`` evening EV charging window (D-04), end-exclusive.
Chosen to overlap the evening winter heating peak in ``DAILY_PATTERN`` (the
17:00-19:00 peak) so EV coincidence binds the firm hosting limit.

Recalibrated 10-03 per CALIBRATION.md "Recommended values": EV daily energy
6-13 kWh (~2 h active, not a flat 5 h block). The 3 active hours (17,18,19) at
2.52 kW coincident give 7.56 kWh/EV/day, mid-band (the prior (17,22) flat 5 h
yielded 21.6 kWh, ~2x the verified Canadian session energy). The flat in-window
shape stays seasonless (Charge-the-North validated)."""

EV_SWEEP = (0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32, 34,
            36, 38, 40, 42, 44, 46, 48, 50, 52)
"""Ascending total-feeder EV counts to sweep (D-07/D-08), integer step 2 from 0
to 52. The swept variable is the TOTAL EV count on the feeder (the headline
units).

Recalibrated 10-03 per CALIBRATION.md "Recommended values": cap to a plausible
adoption (<= ~2 EV/dwelling ~= 52 on 26 dwellings) and refine the step near the
firm-flexible crossing. Step-2 finely resolves the trade curve and brackets the
crossing so a feasible swept point strictly above firm (and below the 1%
curtailed-energy tolerance) is reachable; the prior step-20 grid jumped firm(20)
straight to first-overload(40) and could land no passing point between them."""

CALENDAR_HOURS = 8760
"""Non-leap hour-of-year count (Open-Q3). 365 days x 24 h; the pinned time index
for every annual profile and the Phase-12 hour x line congestion heatmap."""

CALENDAR_START_WEEKDAY = 0
"""Weekday of hour-of-year 0 (Open-Q3), Mon=0 .. Sun=6. Pinned to Monday so the
season->hour mapping is deterministic: day-of-year = ``hour_of_year // 24``,
weekday = ``(day_of_year + CALENDAR_START_WEEKDAY) % 7``; winter (Jan/Dec) sits
at the low/high day-of-year ends, summer (Jul) near day 180."""

# ─── 09-03 (GAP 1): project-local feeder-transformer sizing margin ──────
# APPENDED below the locked Phase-9 envelope contract (do NOT edit any constant
# above). Closes GAP 1 / CONG-03: the deterministically-selected feeder
# transformer is project-locally load-aware sized to its annual winter-peak
# downstream base demand, instead of the fixed 0.21 MVA SDK std_type.

TRANSFORMER_UTILIZATION_MARGIN = 0.8
"""Headroom margin the selected feeder transformer is load-aware sized to (09-03).

Mirrors the line-sizing precedent in
``gridalyn/simulation/simulators/powerflow/line_sizing_select.py`` (required
rating = design load / ``utilization_margin`` reserves headroom at margin 0.8).
The D-08 calibration target follows directly: with the feeder transformer sized
to ``peak_downstream_base_kW / 0.8``, the binding feeder element sits at or below
~80% loading at 0 EVs, so ``firm_ev_count`` is a positive, non-degenerate
denominator before Phase 10 builds the flexible leg. ONLY the selected feeder
transformer is resized (project-local in ``_topology.py`` /
``prepare_topology_cache.py``); the SDK transformer builder and the shared
``configs/grid/config.json`` stay byte-identical (LINESIZE-01)."""

# ─── Phase-10 (FLEX-03): flexible-sweep acceptability tolerance ──────────
# APPENDED below the locked constants (do NOT edit any constant above). These
# pin the FLEX-03 acceptability gate the flexible sweep classifies each swept EV
# count against (feasible AND tolerance); the locked D-12 reproducibility
# contract (LINE_LOADING_LIMIT_PERCENT, DTYPE, SEED, ROUND_DECIMALS, EV_SWEEP,
# POWER_FACTOR) above is untouched.

TOLERANCE_CURTAILED_ENERGY_FRACTION_MAX = 0.01
"""Strict-``<`` primary acceptability gate (D-06): the annual curtailed-energy
fraction must be < 1% for a swept EV count to pass. A point sitting EXACTLY at
this value does NOT pass (strict ``<``, pinned)."""

TOLERANCE_ACTIVATION_HOURS_MAX = 100
"""Secondary acceptability gate (D-06): the max total contract activation hours
a swept EV count may incur and still pass when ``TOLERANCE_PRIMARY`` selects
``"activation_hours"``."""

TOLERANCE_PRIMARY = "curtailed_energy_fraction"
"""Active acceptability-criterion selector (D-06): the only accepted values are
``"curtailed_energy_fraction"`` (the default primary strict-``<`` gate) and
``"activation_hours"`` (the secondary ``<=`` gate)."""
