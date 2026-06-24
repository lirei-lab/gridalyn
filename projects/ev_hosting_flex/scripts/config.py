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
"""DEPRECATED (D-14): superseded by the TMY heating-degree base (see the
Phase-10.1 appended block: ``T_BALANCE`` / ``R_THERM`` / ``BG_KW`` +
``TMY_INPUT_PATH``). Value left unedited (Pitfall 6) — no longer the base-load
driver; retained only so the legacy ``_profiles`` winter envelope and the
``annual_peak_base_factor`` transformer/line subtree sizing path stay importable
and byte-identical until Plan 03/04 fully retires them.

Seasonal winter-peak multiplier on the base envelope (D-03). Cold-climate
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
"""DEPRECATED (D-14): superseded by the TMY heating-degree base. Value left
unedited (Pitfall 6).

Seasonal summer floor of the base envelope (D-03). The seasonal multiplier
interpolates between this trough (Jul) and ``WINTER_PEAK_FACTOR`` (Jan/Dec) so
winter > summer at every hour-of-day."""

DAILY_PATTERN = (
    0.55, 0.50, 0.48, 0.47, 0.48, 0.55,  # 00:00-05:00 overnight base
    0.70, 0.85, 0.80, 0.72, 0.68, 0.66,  # 06:00-11:00 morning ramp
    0.65, 0.64, 0.65, 0.70, 0.82, 1.00,  # 12:00-17:00 building toward peak
    1.05, 1.00, 0.92, 0.80, 0.68, 0.60,  # 18:00-23:00 evening heating peak
)
"""DEPRECATED (D-14): superseded by the TMY heating-degree base. Value left
unedited (Pitfall 6).

24-hour-of-day shape coefficients (D-03), index = ``hour_of_year % 24``. The
evening heating peak (~17:00-21:00) coincides with the EV ``CHARGING_WINDOW`` so
EV coincidence stresses the same hours as the base peak (the firm-limit driver).
"""

WEEKLY_PATTERN = (
    1.00, 0.99, 0.99, 0.99, 1.00, 1.04, 1.05,
)
"""DEPRECATED (D-14): superseded by the TMY heating-degree base. Value left
unedited (Pitfall 6).

7-day-of-week shape coefficients (D-03), Mon=0 .. Sun=6, indexed by weekday
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

# ─── Phase-10.1 (RECAL-01/02/09): HQ-transformer + TMY + stochastic-EV block ──
# APPENDED below the locked constants (do NOT edit any constant above). This is
# the unit-of-congestion + input + stochastic-model spine every Phase-10.1 plan
# consumes (D-01..D-12). It re-points the study from the 26-dwelling aggregated
# subtree to a small HQ residential LV transformer, drives the base from the
# committed Trois-Rivieres TMY (heating-degree model), and pins the calibrated
# stochastic-EV generative knobs (charger mix, lognormal session energy, evening
# arrivals, plug-in probability). The four deterministic-base constants above are
# now deprecated per D-14 (banner in each docstring); values retained byte-unchanged.

TMY_INPUT_PATH = PROJECT_ROOT / "inputs" / "tmy_trois_rivieres.csv"
"""Committed project-local TMY (D-09). PVGIS SARAH-3 Trois-Rivieres copy of the
verified ``flexibility_cls`` TMY, given independent provenance for a
self-contained governed study. Network-free: the heating-degree base reads
``temp_air`` from THIS file — never ``download_tmy()`` / weather source
``"auto"`` (REPRO guard inherited)."""

# ─── HQ residential LV-transformer sizing (D-01/D-03/D-04) ───────────────

TRANSFORMER_KVA = 75.0
"""Modeled nameplate rating (kVA) of the small HQ residential LV transformer that
is now the unit of congestion (D-01).

DEVIATION (checkpoint resolution, 10.1-01): the plan's original must_have framed
this unit as "~50 kVA". The Task-1 twin-inventory probe (``--force-rebuild``)
proved the regenerated twin has NO ~50 kVA MV/LV transformer — every (25/0.4 kV)
unit is a uniform physical 0.21 MVA (210 kVA) nameplate, and the closest-to-6
downstream-home unit is ``trafo_idx=62`` with 7 homes. Per the user's decision we
do NOT pin 50 kVA and do NOT block; instead we model a slightly larger,
appropriate HQ residential rating and pick the smallest standard size in
{75, 100} kVA that makes the transformer a *meaningful* unit of congestion.

Evidence-based pick = 75 kVA (PF=0.95 → 71.25 kW usable; UTIL=0.8 → 57 kW
winter-peak target). For the selected ``trafo_idx=62`` (7 homes) at
``ADMD_KW=6.5``: diversified base/no-EV peak ≈ 7 × 6.5 = 45.5 kW.
  (a) Not congested at K=0 / zero EVs: 45.5 / 71.25 ≈ 64% loading — comfortably
      below the 100% thermal limit (and near the 80% UTIL design target).
  (b) Congests INSIDE the ``PENETRATION_SWEEP``: EV coincident draw ≈ 2.5 kW/EV
      (CALIBRATION.md §3/§5: ~1.4–2.0 kW on large feeders, higher small/cold). At
      ~1 EV/home (7 EVs): 45.5 + 7 × 2.5 ≈ 63 kW → 63 / 71.25 ≈ 88%, crossing the
      congestion threshold around the manuscript's ~1 EV/home headline.
100 kVA was rejected: at 7 EVs it sits at 63 / 95 ≈ 66% and only reaches the
limit near ~2 EV/home (the top of the sweep), making the transformer a far less
meaningful unit of congestion. This rating is DECOUPLED from the twin's physical
210 kVA nameplate (D-02): congestion keys off this modeled rating + downstream
demand, NOT ``net.trafo.sn_mva``; the twin / topology cache / net stay physically
intact."""

ADMD_KW = 6.5
"""After-diversity max demand per all-electric home (kW), small group (D-04).

CALIBRATION.md derivation: per-dwelling installed ~13 kW baseboard nameplate ×
instantaneous thermostat diversity ≈ 0.5 → ~6.5 kW after-diversity coincident for
a small group of all-electric homes (CALIBRATION.md §1/§2; band 10–15 kW
nameplate). Cross-checked against the design-cold heating-degree path below:
``(T_BALANCE − (−25)) / R_THERM + BG_KW ≈ (18 − (−25)) / 8.1 + 1.2 ≈ 5.3 + 1.2 ≈
6.5 kW/home`` — the two derivations agree. Reconciled to the manuscript's
6.5 kW/home anchor (D-04)."""

UTIL = 0.8
"""Winter-peak base utilization target on ``TRANSFORMER_KVA`` (manuscript KNOB,
mirrors ``TRANSFORMER_UTILIZATION_MARGIN``). The diversified winter base loads the
modeled transformer to ~80% of its usable kW at the cold-evening peak, reserving
CLPU headroom (CALIBRATION.md §4: 0.8 is the defensible HQ value)."""

TARGET_HOMES = 6
"""Manuscript-intent target downstream-home count for feeder re-pointing (D-03).

``select_feeder`` ranks the MV/LV (25/0.4 kV) transformers by
``abs(downstream_home_count − TARGET_HOMES)`` ascending and picks the closest
(Option C, robust to twin regeneration). In the current twin the closest unit is
``trafo_idx=62`` with 7 homes (none reaches exactly 6; candidates: idx 62 → 7,
idx 43/46/188 → 8). The modeled ``_homes = round(UTIL·TRANSFORMER_KVA·PF/ADMD)``
relationship from the standalone manuscript MC is DECOUPLED here: the physical
downstream home count (7) comes from the twin, not the formula (which at 75 kVA
would yield ~9). Congestion is computed on the twin's real 7-home subtree."""

# ─── Stochastic-EV generative model (D-05, manuscript-calibrated) ────────

CHARGER_MIX = {7.2: 0.75, 9.6: 0.20, 11.5: 0.05}
"""Quebec residential charger-power mix (kW → share), manuscript-calibrated:
7.2 kW L2 dominant, 9.6 kW minority, 11.5 kW a small stress fraction. Shares sum
to 1.0; sampled per EV in the stochastic generative model (Plan 02)."""

EV_KWH_MEDIAN = 8.0
"""Lognormal median daily EV charging energy (kWh) (manuscript KNOB). Mid of the
CALIBRATION.md §5 Canadian 6–13 kWh/session band."""

EV_KWH_SIGMA = 0.5
"""Lognormal sigma (log-space) of daily EV charging energy (manuscript KNOB)."""

EV_KWH_MIN = 1.0
"""Floor (kWh) clipping the sampled daily EV charging energy (manuscript KNOB)."""

PLUGIN_PROB = 0.65
"""Probability an EV charges on a given evening (manuscript KNOB). CALIBRATION.md
§5: EVs are plugged ~11 h but drawing only ~2 h, and not every evening."""

ARRIVAL_MEAN_H = 18.0
"""Mean evening EV arrival hour (manuscript KNOB). CALIBRATION.md §5: residential
charging peaks 15:00–24:00 ("EV duck curve"), overlapping the heating peak."""

ARRIVAL_STD_H = 1.5
"""Std-dev (hours) of the Gaussian EV arrival time (manuscript KNOB)."""

ARRIVAL_CLIP = (16.0, 22.0)
"""``(min, max)`` clip on the sampled EV arrival hour (manuscript KNOB)."""

# ─── TMY heating-degree base (D-08, manuscript-calibrated) ───────────────

T_BALANCE = 18.0
"""Heating balance point (degC) of the heating-degree base model (D-08). Per-home
heating load = ``max(0, T_BALANCE − T_out) / R_THERM`` (+ background). Manuscript
anchor, reconciled to CALIBRATION.md §2."""

R_THERM = 8.1
"""Per-home thermal envelope resistance (degC/kW) (D-08). Design-cold check:
``(18 − (−25)) / 8.1 ≈ 5.3 kW`` heating + ``BG_KW`` ≈ 6.5 kW/home, matching
``ADMD_KW`` and CALIBRATION.md §2 (~6 kW heat at −25 degC + ~1.5 kW background)."""

BG_KW = 1.2
"""Per-home non-heating background load (kW), occupancy-shaped (D-08). Manuscript
anchor; with the heating-degree term gives ~6.5 kW/home at design cold."""

PLUGIN_WINDOW = (18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5, 6, 7)
"""Hours an EV is physically present and may host deferred energy (D-11). The
wrap-midnight ~18:00 arrival → ~07:00 departure plug-in window (~11 h plugged vs
~2 h charging, CALIBRATION.md §5). Deferral (valley-fill) may only re-place EV
energy in hours inside this set — NOT a fixed off-peak ``[22..6]`` block (which
ignores early departures, D-11)."""

# ─── Monte-Carlo + penetration sweep (D-05/D-07, discretion) ─────────────

K = 1000
"""Monte-Carlo realizations per penetration point (D-05, Claude's discretion;
manuscript used 1500–2000). Default 1000 — the smallest K targeted to keep P95
stable to the Phase-12 1e-6 baseline while staying fast over 8760 h. Part of the
reproducibility contract with ``SEED`` (D-13); revisit in Plan 02 if P95 drifts."""

PENETRATION_SWEEP = (
    0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0,
    1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 2.0,
)
"""EV-per-home penetration grid (0 → 2.0) swept on the small LV transformer
(D-07, discretion). Supersedes the Phase-9 integer ``EV_SWEEP`` (a total-feeder
count on 26 dwellings). The headline is also expressed as an EV count
(``round(penetration × downstream_home_count)``). Step 0.1 finely brackets the
firm/flexible crossing near the manuscript's ~1 EV/home congestion onset."""

# ─── Re-calibrated firm / flexible acceptability gates (D-06/D-12) ───────

FIRM_PCONG_TOLERANCE = 0.10
"""Firm-leg congestion-probability tolerance (D-06). ``firm`` = the largest
adoption whose ``P(congestion) ≤ 10%`` (probability of ANY hour exceeding the
LV-transformer rating over the K realizations). Replaces the Phase-9 CONG-03
"zero overloads at any hour" definition, which collapses to ~0 under the
cold-evening tail. Mirrors the existing ``TOLERANCE_*`` style."""

TOLERANCE_IRREDUCIBLE_LOST_FRACTION_MAX_P95 = 0.01
"""Flexible-leg (deferral) acceptability gate (D-12, FLEX-03 successor). The
irreducible-lost-energy fraction — energy that fits in NEITHER the congested hour
NOR any in-window valley (the ``remaining`` after valley-fill deferral) divided by
annual EV demand — must be strict-``<`` 1% at P95 for a swept point to pass. The
curtailment curve keeps its own ``TOLERANCE_CURTAILED_ENERGY_FRACTION_MAX``."""

# ─── Phase-10.2 (TWOSTAGE-01..07, D-01..D-10): two-stage stochastic program ──
# APPEND-ONLY block below the locked Phase-10.1 constants (everything above —
# through ``TOLERANCE_IRREDUCIBLE_LOST_FRACTION_MAX_P95`` — is byte-frozen, mirrors
# RECAL-09). These pin the two-stage chance-constrained EV-curtailment program:
# day-ahead reservation of a reliability quantile (``r_t = Q_{1−ε}[required_t]``)
# + real-time activation recourse (``a_t = min(r_t, required_t)``) over scenarios
# carrying day-ahead temperature-forecast error + the Phase-10.1 stochastic EV
# model. The closed-form policy is the byte-stable reproducibility ORACLE the
# gated cvxpy solve (D-08) must match to ≤1e-6. Reuses the locked ``SEED``,
# ``DTYPE``, ``ROUND_DECIMALS``, ``TRANSFORMER_KVA``, ``POWER_FACTOR``,
# ``T_BALANCE``, ``R_THERM``, ``BG_KW``, the charger/arrival knobs,
# ``TMY_INPUT_PATH`` and ``CALENDAR_HOURS`` (do NOT redefine them).

EPS_HEADLINE = 0.05
"""Fixed per-hour reliability operating point for the citable hosting headline
(D-04/D-07). The optimal ``flexible_ev_count`` / ``hosting_expansion_percent`` are
re-derived under the two-stage scheme at ``1 − EPS_HEADLINE = 95%`` per-hour
reliability — a single fixed ε is required for a citable number (chosen over a
frontier-only result)."""

EPS_FRONTIER = (0.5, 0.4, 0.3, 0.2, 0.15, 0.10, 0.05, 0.02, 0.01)
"""Cost-vs-reliability sensitivity sweep (D-04). The supporting ε-grid traced for
the frontier; reliability ``1 − ε`` rises monotonically as ε falls. Reported as
sensitivity evidence around the ``EPS_HEADLINE`` operating point."""

EPS_SHOW = 0.10
"""Reserve-vs-activation cold-day panel epsilon (D-07). The mechanism-evidence
panel (day-ahead ``r_t`` vs real-time ``E[a_t]``) is drawn at this ε — the
prototype's ``EPS_SHOW`` (``twostage_prototype.py`` L42), where activation ≈ ¼ of
the reserved peak illustrates "reserve the tail, activate only what is needed"."""

SIGMA_DAILY = 2.0
"""Day-ahead temperature-forecast per-day offset std in °C (D-03). One ``N(0,
SIGMA_DAILY)`` draw per scenario perturbs the whole cold TMY day uniformly — the
unknown-day-ahead weather component that makes the scheme genuinely
two-stage-under-uncertainty. Prototype ``TEMP_FCAST_OFFSET_STD``."""

SIGMA_HOURLY = 0.8
"""Per-hour temperature-forecast noise std in °C (D-03). A 24-vector ``N(0,
SIGMA_HOURLY)`` draw per scenario adds hourly weather noise on top of the daily
offset. Prototype ``TEMP_FCAST_HOURLY_STD``."""

N_SCENARIOS = 4000
"""Monte-Carlo scenario count for the per-hour quantile estimates (D-10). Large
enough for stable tail quantiles at the tightest ε=0.01. Reconciles the divergent
prototype seeds/counts (``twostage_prototype.py`` N=4000 / ``breakeven_nonwires``
N=1000) to a single reproducibility contract on ``SEED=42``."""

C_RESERVE = 0.5
"""ILLUSTRATIVE labelled reservation price per kW·h reserved day-ahead (D-06).
The optimal policy (``r* = Q_{1−ε}``, ``a* = min``) is PRICE-INDEPENDENT as long
as ``C_ACTIVATE > 0`` — this price only SCALES the separately-reported, clearly
illustrative cost frontier, it does not move the hosting headline or the
reliability guarantee. Prototype ``C_R``. The break-even phase's different prices
(``breakeven_nonwires.py``) are NOT used here (RESEARCH A5)."""

C_ACTIVATE = 2.0
"""ILLUSTRATIVE labelled activation price per kW·h activated in real time (D-06).
As with ``C_RESERVE``, illustrative-only: the optimum is price-independent for any
``C_ACTIVATE > 0`` and this merely scales the reported frontier. Prototype
``C_A``. Real economic crossing vs reinforcement CAPEX is deferred to the
break-even phase (D-01) with its own prices."""

TWOSTAGE_SOLVER = "CLARABEL"
"""Single pinned deterministic cvxpy solver for the gated two-stage solve (D-08).
CLARABEL is the project default (``der_voltage.py``) and is present in this env
(``cvxpy.installed_solvers() == ['CLARABEL','HIGHS','OSQP','SCIPY','SCS']``).
ECOS is DROPPED — D-08's "ECOS fallback" wording is refined (RESEARCH Open-Q1 /
Pitfall 5) because ECOS is NOT installed here; the closed-form oracle is the sole
fallback (D-08c). The cvxpy solve must reproduce the oracle to ≤1e-6 or the stage
falls back to the oracle and records the divergence."""
