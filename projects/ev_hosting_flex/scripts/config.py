"""Centralized EV Hosting Flex project configuration.

Locks the reproducibility and threshold conventions every later stage of the
``ev_hosting_flex`` pipeline inherits (decisions D-02, D-05, D-06, D-07). The
flattened module-level constants below are the contract: ``_topology_helpers.py``
(the study-local feeder-selection/envelope helpers) and the stage scripts import
them directly; the generic radial-feeder analytics resolve from the SDK
``gridalyn.simulation.analytics.topology`` (Plan 20-03).
"""

import json
from pathlib import Path

import yaml as _yaml

ROOT = Path(__file__).parents[3]
PROJECT_ROOT = ROOT / "projects" / "ev_hosting_flex"
PROJECT_OUTPUTS_DIR = PROJECT_ROOT / "outputs"
PROJECT_CACHE_DIR = PROJECT_OUTPUTS_DIR / "cache"
TOPOLOGY_CACHE_MANIFEST = PROJECT_CACHE_DIR / "topology_cache_manifest.json"

# ─── Load the underlying physical system configuration ──────────────────
# Project-local mirror of ``configs/grid/config.json`` that opts into
# ``lines.sizing.mode = "load_aware"`` (08.1-02). Keeping a SEPARATE file leaves
# the shared ``configs/grid/config.json`` byte-identical so the tutorials and
# test_line_sizing_diagnostic stay green (LINESIZE-01).
GRID_CONFIG_PATH = PROJECT_ROOT / "inputs" / "synthetic_network_config.json"
with open(GRID_CONFIG_PATH) as f:
    GRID_CONFIG = json.load(f)


# ─── Config-as-contract (Phase 20): project.yaml is the single source of truth ─
# The study values are declared under spec.inputs.studyConfig in project.yaml;
# this module reads them through located errors (never a bare KeyError), so a
# dropped block or a missing key is diagnosable from the message. Paths/layout,
# the GRID_CONFIG JSON load, and the derived constants below remain code: they
# are layout or computed relationships, not study parameters.

_PROJECT_FILE = PROJECT_ROOT / "project.yaml"


def _study_config() -> dict:
    """Load the declared ``spec.inputs.studyConfig`` block from project.yaml.

    Raises:
        ValueError: A located error naming the project file and the input key
            when ``studyConfig`` is absent or not a mapping.
    """
    raw = _yaml.safe_load(_PROJECT_FILE.read_text(encoding="utf-8"))
    inputs = (raw or {}).get("spec", {}).get("inputs", {})
    if not isinstance(inputs, dict) or "studyConfig" not in inputs:
        available = ", ".join(sorted(str(k) for k in inputs)) or "none declared"
        raise ValueError(
            f"{_PROJECT_FILE}: spec.inputs.studyConfig not found "
            f"(available inputs: {available}). Remediation: declare the study "
            "knobs under spec.inputs.studyConfig in project.yaml."
        )
    config = inputs["studyConfig"]
    if not isinstance(config, dict):
        raise ValueError(
            f"{_PROJECT_FILE}: spec.inputs.studyConfig must be a mapping, "
            f"found {type(config).__name__}"
        )
    return config


class _LocatedStudyConfig(dict):
    """A ``studyConfig`` mapping whose missing-key errors are located.

    A bare ``KeyError: 'seed'`` names neither the file nor the fix; every
    ``_CONFIG[...]`` access through this mapping raises a ``ValueError`` that
    does both.
    """

    def __getitem__(self, key: object) -> object:
        if key not in self:
            available = ", ".join(sorted(str(k) for k in self)) or "none declared"
            raise ValueError(
                f"{_PROJECT_FILE}: spec.inputs.studyConfig.{key} not found "
                f"(available studyConfig keys: {available}). Remediation: add "
                "the missing knob to spec.inputs.studyConfig in project.yaml."
            )
        return super().__getitem__(key)


_CONFIG = _LocatedStudyConfig(_study_config())

# ─── Phase-8 locked reproducibility + threshold conventions ─────────────

# These are flattened module-level constants (the contract for downstream
# stages). A nested PROJECT_CONFIG dict can grow later for grouping, but the
# flat names below are what every consumer imports.

POWER_FACTOR = _CONFIG["powerFactor"]
"""Power factor for BOTH line and transformer kW conversion (D-05, A4)."""

LINE_LOADING_LIMIT_PERCENT = _CONFIG["lineLoadingLimitPercent"]
"""Thermal loading limit (%) above which a line is congested (D-06)."""

DTYPE = _CONFIG["dtype"]
"""Float dtype used throughout every numeric path (D-07)."""

SEED = _CONFIG["seed"]
"""Single pinned seed. Consume via ``np.random.default_rng(SEED)`` — NEVER the
global ``np.random.seed`` (D-07)."""

ROUND_DECIMALS = _CONFIG["roundDecimals"]
"""Pre-write rounding so float noise < 1e-6 never reaches the Phase-12
regression comparator (D-07)."""

FEEDER_ID = _CONFIG["feederId"]
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
    0.55,
    0.50,
    0.48,
    0.47,
    0.48,
    0.55,  # 00:00-05:00 overnight base
    0.70,
    0.85,
    0.80,
    0.72,
    0.68,
    0.66,  # 06:00-11:00 morning ramp
    0.65,
    0.64,
    0.65,
    0.70,
    0.82,
    1.00,  # 12:00-17:00 building toward peak
    1.05,
    1.00,
    0.92,
    0.80,
    0.68,
    0.60,  # 18:00-23:00 evening heating peak
)
"""DEPRECATED (D-14): superseded by the TMY heating-degree base. Value left
unedited (Pitfall 6).

24-hour-of-day shape coefficients (D-03), index = ``hour_of_year % 24``. The
evening heating peak (~17:00-21:00) coincides with the EV ``CHARGING_WINDOW`` so
EV coincidence stresses the same hours as the base peak (the firm-limit driver).
"""

WEEKLY_PATTERN = (
    1.00,
    0.99,
    0.99,
    0.99,
    1.00,
    1.04,
    1.05,
)
"""DEPRECATED (D-14): superseded by the TMY heating-degree base. Value left
unedited (Pitfall 6).

7-day-of-week shape coefficients (D-03), Mon=0 .. Sun=6, indexed by weekday
derived from ``CALENDAR_START_WEEKDAY``. Weekends carry slightly higher
residential occupancy load."""

EV_UNIT_KW = _CONFIG["evUnitKw"]
"""Per-EV charging power in kW (D-05). A typical residential 240 V / 32 A AC
Level-2 charger draws ~7.2 kW at full power. Kept at the L2 nameplate per
CALIBRATION.md (the coincident draw is set via ``DIVERSITY_FACTOR``, not by
lowering the nameplate)."""

DIVERSITY_FACTOR = _CONFIG["diversityFactor"]
"""Simultaneous-draw fraction at the evening peak (D-05, Pitfall 5). Not all EVs
charge at once; this is the coincident fraction applied to the per-EV unit draw.

Recalibrated 10-03 per CALIBRATION.md "Recommended values": EV coincident power
``EV_UNIT_KW x DIVERSITY_FACTOR`` toward ~2-3 kW. At 0.35 the coincident draw is
7.2 x 0.35 = 2.52 kW, mid-band (the prior 0.6 yielded 4.32 kW, the verified
high-end). Canadian diversified is ~1.4 kW on large feeders, raised here for a
small/cold 26-dwelling feeder. Deliberately NOT 1.0 (over-pessimistic) and NOT
negligible."""

CHARGING_WINDOW = tuple(_CONFIG["chargingWindow"])
"""``(start_hour, end_hour)`` evening EV charging window (D-04), end-exclusive.
Chosen to overlap the evening winter heating peak in ``DAILY_PATTERN`` (the
17:00-19:00 peak) so EV coincidence binds the firm hosting limit.

Recalibrated 10-03 per CALIBRATION.md "Recommended values": EV daily energy
6-13 kWh (~2 h active, not a flat 5 h block). The 3 active hours (17,18,19) at
2.52 kW coincident give 7.56 kWh/EV/day, mid-band (the prior (17,22) flat 5 h
yielded 21.6 kWh, ~2x the verified Canadian session energy). The flat in-window
shape stays seasonless (Charge-the-North validated)."""

EV_SWEEP = tuple(_CONFIG["evSweep"])
"""Ascending total-feeder EV counts to sweep (D-07/D-08), integer step 2 from 0
to 52. The swept variable is the TOTAL EV count on the feeder (the headline
units).

Recalibrated 10-03 per CALIBRATION.md "Recommended values": cap to a plausible
adoption (<= ~2 EV/dwelling ~= 52 on 26 dwellings) and refine the step near the
firm-flexible crossing. Step-2 finely resolves the trade curve and brackets the
crossing so a feasible swept point strictly above firm (and below the 1%
curtailed-energy tolerance) is reachable; the prior step-20 grid jumped firm(20)
straight to first-overload(40) and could land no passing point between them."""

CALENDAR_HOURS = _CONFIG["calendarHours"]
"""Non-leap hour-of-year count (Open-Q3). 365 days x 24 h; the pinned time index
for every annual profile and the Phase-12 hour x line congestion heatmap."""

CALENDAR_START_WEEKDAY = _CONFIG["calendarStartWeekday"]
"""Weekday of hour-of-year 0 (Open-Q3), Mon=0 .. Sun=6. Pinned to Monday so the
season->hour mapping is deterministic: day-of-year = ``hour_of_year // 24``,
weekday = ``(day_of_year + CALENDAR_START_WEEKDAY) % 7``; winter (Jan/Dec) sits
at the low/high day-of-year ends, summer (Jul) near day 180."""

# ─── 09-03 (GAP 1): project-local feeder-transformer sizing margin ──────
# APPENDED below the locked Phase-9 envelope contract (do NOT edit any constant
# above). Closes GAP 1 / CONG-03: the deterministically-selected feeder
# transformer is project-locally load-aware sized to its annual winter-peak
# downstream base demand, instead of the fixed 0.21 MVA SDK std_type.

TRANSFORMER_UTILIZATION_MARGIN = _CONFIG["transformerUtilizationMargin"]
"""Headroom margin the selected feeder transformer is load-aware sized to (09-03).

Mirrors the line-sizing precedent in
``gridalyn/simulation/simulators/powerflow/line_sizing_select.py`` (required
rating = design load / ``utilization_margin`` reserves headroom at margin 0.8).
The D-08 calibration target follows directly: with the feeder transformer sized
to ``peak_downstream_base_kW / 0.8``, the binding feeder element sits at or below
~80% loading at 0 EVs, so ``firm_ev_count`` is a positive, non-degenerate
denominator before Phase 10 builds the flexible leg. ONLY the selected feeder
transformer is resized (project-local in ``prepare_topology_cache.py``, using the
SDK ``gridalyn.simulation.analytics.topology`` sizing + the study-local
``_topology_helpers`` — the former ``_topology.py`` copy was deleted in Plan
20-03); the SDK transformer builder and the shared
``configs/grid/config.json`` stay byte-identical (LINESIZE-01)."""

# ─── Phase-10 (FLEX-03): flexible-sweep acceptability tolerance ──────────
# APPENDED below the locked constants (do NOT edit any constant above). These
# pin the FLEX-03 acceptability gate the flexible sweep classifies each swept EV
# count against (feasible AND tolerance); the locked D-12 reproducibility
# contract (LINE_LOADING_LIMIT_PERCENT, DTYPE, SEED, ROUND_DECIMALS, EV_SWEEP,
# POWER_FACTOR) above is untouched.

TOLERANCE_CURTAILED_ENERGY_FRACTION_MAX = 0.01
"""RETIRED (Phase 15 RETIRE-02, D-13): the energy-fraction acceptability gate is
removed from the pipeline path — Phase 15 gates ``flexible_ev_count`` on realized
``P(overload) ≤ ε`` ALONE; energy is reported, never gated. KEPT importable this
plan because the retired ``_flexibility.flexible_ev_count`` default + the stage-5
``apply_flexibility_contracts`` body still reference it; physically deleted in
Plan 03 when that body + ``_flexibility.py`` are removed (banner-now /
delete-when-import-gone, Pitfall 3).

Strict-``<`` primary acceptability gate (D-06): the annual curtailed-energy
fraction must be < 1% for a swept EV count to pass. A point sitting EXACTLY at
this value does NOT pass (strict ``<``, pinned)."""

TOLERANCE_ACTIVATION_HOURS_MAX = 100
"""RETIRED (Phase 15 RETIRE-02, D-13): a secondary energy/activation acceptability
gate; removed from the pipeline path (reliability-only gating). KEPT importable
this plan (referenced by ``_flexibility.flexible_ev_count`` default); physically
deleted in Plan 03 with ``_flexibility.py``.

Secondary acceptability gate (D-06): the max total contract activation hours
a swept EV count may incur and still pass when ``TOLERANCE_PRIMARY`` selects
``"activation_hours"``."""

TOLERANCE_PRIMARY = "curtailed_energy_fraction"
"""RETIRED (Phase 15 RETIRE-02, D-13): the energy/activation acceptability-criterion
selector; removed from the pipeline path (reliability-only gating). KEPT importable
this plan (referenced by ``_flexibility.flexible_ev_count`` default); physically
deleted in Plan 03 with ``_flexibility.py``.

Active acceptability-criterion selector (D-06): the only accepted values are
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
"""Committed project-local TMY (D-09). PVGIS SARAH-3 Trois-Rivieres, committed
with independent provenance for a self-contained governed study. Network-free:
the heating-degree base reads ``temp_air`` from THIS file — never
``download_tmy()`` / weather source ``"auto"`` (REPRO guard inherited)."""

# ─── HQ residential LV-transformer sizing (D-01/D-03/D-04) ───────────────

TRANSFORMER_KVA = _CONFIG["transformerKva"]
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

ADMD_KW = _CONFIG["admdKw"]
"""After-diversity max demand per all-electric home (kW), small group (D-04).

CALIBRATION.md derivation: per-dwelling installed ~13 kW baseboard nameplate ×
instantaneous thermostat diversity ≈ 0.5 → ~6.5 kW after-diversity coincident for
a small group of all-electric homes (CALIBRATION.md §1/§2; band 10–15 kW
nameplate). Cross-checked against the design-cold heating-degree path below:
``(T_BALANCE − (−25)) / R_THERM + BG_KW ≈ (18 − (−25)) / 8.1 + 1.2 ≈ 5.3 + 1.2 ≈
6.5 kW/home`` — the two derivations agree. Reconciled to the manuscript's
6.5 kW/home anchor (D-04)."""

UTIL = _CONFIG["util"]
"""Winter-peak base utilization target on ``TRANSFORMER_KVA`` (manuscript KNOB,
mirrors ``TRANSFORMER_UTILIZATION_MARGIN``). The diversified winter base loads the
modeled transformer to ~80% of its usable kW at the cold-evening peak, reserving
CLPU headroom (CALIBRATION.md §4: 0.8 is the defensible HQ value)."""

TARGET_HOMES = _CONFIG["targetHomes"]
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

CHARGER_MIX = _CONFIG["chargerMix"]
"""Quebec residential charger-power mix (kW → share), manuscript-calibrated:
7.2 kW L2 dominant, 9.6 kW minority, 11.5 kW a small stress fraction. Shares sum
to 1.0; sampled per EV in the stochastic generative model (Plan 02)."""

EV_KWH_MEDIAN = _CONFIG["evKwhMedian"]
"""Lognormal median daily EV charging energy (kWh) (manuscript KNOB). Mid of the
CALIBRATION.md §5 Canadian 6–13 kWh/session band."""

EV_KWH_SIGMA = _CONFIG["evKwhSigma"]
"""Lognormal sigma (log-space) of daily EV charging energy (manuscript KNOB)."""

EV_KWH_MIN = _CONFIG["evKwhMin"]
"""Floor (kWh) clipping the sampled daily EV charging energy (manuscript KNOB)."""

PLUGIN_PROB = _CONFIG["pluginProb"]
"""Probability an EV charges on a given evening (manuscript KNOB). CALIBRATION.md
§5: EVs are plugged ~11 h but drawing only ~2 h, and not every evening."""

ARRIVAL_MEAN_H = _CONFIG["arrivalMeanH"]
"""Mean evening EV arrival hour (manuscript KNOB). CALIBRATION.md §5: residential
charging peaks 15:00–24:00 ("EV duck curve"), overlapping the heating peak."""

ARRIVAL_STD_H = _CONFIG["arrivalStdH"]
"""Std-dev (hours) of the Gaussian EV arrival time (manuscript KNOB)."""

ARRIVAL_CLIP = tuple(_CONFIG["arrivalClip"])
"""``(min, max)`` clip on the sampled EV arrival hour (manuscript KNOB)."""

# ─── TMY heating-degree base (D-08, manuscript-calibrated) ───────────────

T_BALANCE = _CONFIG["tBalance"]
"""Heating balance point (degC) of the heating-degree base model (D-08). Per-home
heating load = ``max(0, T_BALANCE − T_out) / R_THERM`` (+ background). Manuscript
anchor, reconciled to CALIBRATION.md §2."""

R_THERM = _CONFIG["rTherm"]
"""Per-home thermal envelope resistance (degC/kW) (D-08). Design-cold check:
``(18 − (−25)) / 8.1 ≈ 5.3 kW`` heating + ``BG_KW`` ≈ 6.5 kW/home, matching
``ADMD_KW`` and CALIBRATION.md §2 (~6 kW heat at −25 degC + ~1.5 kW background)."""

BG_KW = _CONFIG["bgKw"]
"""Per-home non-heating background load (kW), occupancy-shaped (D-08). Manuscript
anchor; with the heating-degree term gives ~6.5 kW/home at design cold."""

PLUGIN_WINDOW = (18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5, 6, 7)
"""RETIRED (Phase 15 RETIRE-02, D-13): the deferral/availability plug-in window is
removed from the pipeline path (the controller activates ``a_t = min(r_t,
required)`` directly, no deferral session machinery). KEPT importable this plan
because the retired ``_flexibility.flex_deferral``/``flex_power_limited`` legs
still reference it; physically deleted in Plan 03 with ``_flexibility.py``
(banner-now / delete-when-import-gone, Pitfall 3).

Hours an EV is physically present and may host deferred energy (D-11). The
wrap-midnight ~18:00 arrival → ~07:00 departure plug-in window (~11 h plugged vs
~2 h charging, CALIBRATION.md §5). Deferral (valley-fill) may only re-place EV
energy in hours inside this set — NOT a fixed off-peak ``[22..6]`` block (which
ignores early departures, D-11)."""

# ─── Monte-Carlo + penetration sweep (D-05/D-07, discretion) ─────────────

K = 1000
"""RETIRED (Phase 15 RETIRE-02, D-13): the retired annual Monte-Carlo realization
count. The design-day path uses ``K_DESIGN = 60`` (read from ``q_real.shape[0]``,
never ``config.K``). KEPT importable this plan because the stage-6
``solve_twostage_program`` body + ``test_ev_hosting_flex_twostage`` still reference
it; physically deleted in Plan 02 when stage 6 re-points off the annual stack.

Monte-Carlo realizations per penetration point (D-05, Claude's discretion;
manuscript used 1500–2000). Default 1000 — the smallest K targeted to keep P95
stable to the Phase-12 1e-6 baseline while staying fast over 8760 h. Part of the
reproducibility contract with ``SEED`` (D-13); revisit in Plan 02 if P95 drifts."""

PENETRATION_SWEEP = tuple(_CONFIG["penetrationSweep"])
"""EV-per-home penetration grid (0 → 2.0) swept on the small LV transformer
(D-07, discretion). Supersedes the Phase-9 integer ``EV_SWEEP`` (a total-feeder
count on 26 dwellings). The headline is also expressed as an EV count
(``round(penetration × downstream_home_count)``). Step 0.1 finely brackets the
firm/flexible crossing near the manuscript's ~1 EV/home congestion onset."""

# ─── Re-calibrated firm / flexible acceptability gates (D-06/D-12) ───────

FIRM_PCONG_TOLERANCE = _CONFIG["firmPcongTolerance"]
"""Firm-leg congestion-probability tolerance (D-06). ``firm`` = the largest
adoption whose ``P(congestion) ≤ 10%`` (probability of ANY hour exceeding the
LV-transformer rating over the K realizations). Replaces the Phase-9 CONG-03
"zero overloads at any hour" definition, which collapses to ~0 under the
cold-evening tail. Mirrors the existing ``TOLERANCE_*`` style."""

TOLERANCE_IRREDUCIBLE_LOST_FRACTION_MAX_P95 = 0.01
"""RETIRED (Phase 15 RETIRE-02, D-13): the deferral energy-fraction acceptability
gate; removed from the pipeline path (reliability-only gating). KEPT importable
this plan because the stage-6 ``solve_twostage_program`` body still references it;
physically deleted in Plan 02 when stage 6 re-points off the deferral path.

Flexible-leg (deferral) acceptability gate (D-12, FLEX-03 successor). The
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

EPS_HEADLINE = _CONFIG["epsHeadline"]
"""Fixed per-hour reliability operating point for the citable hosting headline
(D-04/D-07). The optimal ``flexible_ev_count`` / ``hosting_expansion_percent`` are
re-derived under the two-stage scheme at ``1 − EPS_HEADLINE = 95%`` per-hour
reliability — a single fixed ε is required for a citable number (chosen over a
frontier-only result)."""

EPS_FRONTIER = tuple(_CONFIG["epsFrontier"])
"""Cost-vs-reliability sensitivity sweep (D-04). The supporting ε-grid traced for
the frontier; reliability ``1 − ε`` rises monotonically as ε falls. Reported as
sensitivity evidence around the ``EPS_HEADLINE`` operating point."""

EPS_SHOW = _CONFIG["epsShow"]
"""Reserve-vs-activation cold-day panel epsilon (D-07). The mechanism-evidence
panel (day-ahead ``r_t`` vs real-time ``E[a_t]``) is drawn at this ε — the
prototype's ``EPS_SHOW`` (``twostage_prototype.py`` L42), where activation ≈ ¼ of
the reserved peak illustrates "reserve the tail, activate only what is needed"."""

SIGMA_DAILY = _CONFIG["sigmaDaily"]
"""Day-ahead temperature-forecast per-day offset std in °C (D-03). One ``N(0,
SIGMA_DAILY)`` draw per scenario perturbs the whole cold TMY day uniformly — the
unknown-day-ahead weather component that makes the scheme genuinely
two-stage-under-uncertainty. Prototype ``TEMP_FCAST_OFFSET_STD``."""

SIGMA_HOURLY = _CONFIG["sigmaHourly"]
"""Per-hour temperature-forecast noise std in °C (D-03). A 24-vector ``N(0,
SIGMA_HOURLY)`` draw per scenario adds hourly weather noise on top of the daily
offset. Prototype ``TEMP_FCAST_HOURLY_STD``."""

N_SCENARIOS = _CONFIG["nScenarios"]
"""Monte-Carlo scenario count for the per-hour quantile estimates (D-10). Large
enough for stable tail quantiles at the tightest ε=0.01. Reconciles the divergent
prototype seeds/counts (``twostage_prototype.py`` N=4000 / ``breakeven_nonwires``
N=1000) to a single reproducibility contract on ``SEED=42``."""

C_RESERVE = _CONFIG["cReserve"]
"""ILLUSTRATIVE labelled reservation price per kW·h reserved day-ahead (D-06).
The optimal policy (``r* = Q_{1−ε}``, ``a* = min``) is PRICE-INDEPENDENT as long
as ``C_ACTIVATE > 0`` — this price only SCALES the separately-reported, clearly
illustrative cost frontier, it does not move the hosting headline or the
reliability guarantee. Prototype ``C_R``. The break-even / deferral prices are now
the governed ECON-02 constants ``C_R_BASE`` / ``C_A`` (Phase 16, D-16-4);
``C_RESERVE`` remains the two-stage frontier-scaling price and is distinct from
them."""

C_ACTIVATE = _CONFIG["cActivate"]
"""ILLUSTRATIVE labelled activation price per kW·h activated in real time (D-06).
As with ``C_RESERVE``, illustrative-only: the optimum is price-independent for any
``C_ACTIVATE > 0`` and this merely scales the reported frontier. Prototype
``C_A``. The real economic crossing vs reinforcement CAPEX is the governed ECON-02
constants ``C_A`` / ``CAPEX_UPGRADE`` (Phase 16, D-16-4); ``C_ACTIVATE`` remains the
two-stage frontier-scaling price and is distinct from them."""

TWOSTAGE_SOLVER = _CONFIG["twostageSolver"]
"""Single pinned deterministic cvxpy solver for the gated two-stage solve (D-08).
CLARABEL is the project default (``der_voltage.py``) and is present in this env
(``cvxpy.installed_solvers() == ['CLARABEL','HIGHS','OSQP','SCIPY','SCS']``).
ECOS is DROPPED — D-08's "ECOS fallback" wording is refined (RESEARCH Open-Q1 /
Pitfall 5) because ECOS is NOT installed here; the closed-form oracle is the sole
fallback (D-08c). The cvxpy solve must reproduce the oracle to ≤1e-6 or the stage
falls back to the oracle and records the divergence."""

# ─── Phase-10.3 (DAYTIME-01..06): power-limited multi-session availability ───
# APPEND-ONLY block below the locked 10.1/10.2 blocks; do NOT redefine
# PLUGIN_WINDOW, DTYPE, ROUND_DECIMALS, K, PENETRATION_SWEEP, TOLERANCE_* (every
# constant above — through ``TWOSTAGE_SOLVER`` — is byte-frozen, mirroring
# RECAL-09 / TWOSTAGE-07). These pin the power-limited natural-charging
# (V1G smart-charging) flexible leg that REPLACES the 10.1 valley-fill deferral
# mechanism: each hour the aggregate EV draw is throttled to
# ``min(draw, max(0, rating − base))``, chronologically per availability session,
# with undelivered energy carried forward to the day's next session. Energy still
# undelivered after the day's last session is the unserved energy. The leg is
# re-baselined under three availability scenarios (overnight / +workplace[9-16] /
# all-day ceiling) on the locked idx-62 71.25 kW / 7-home unit (Plan 02).

WORKPLACE_WINDOW = (9, 10, 11, 12, 13, 14, 15, 16)
"""RETIRED (Phase 15 RETIRE-02, D-13): the power-limited availability-sweep window
is removed from the pipeline path (the controller replaces the availability sweep).
KEPT importable this plan because the stage-5 ``apply_flexibility_contracts`` body +
``AVAILABILITY_SCENARIOS`` still reference it; physically deleted in Plan 03 when
that body is removed (banner-now / delete-when-import-gone, Pitfall 3).

Daytime workplace plug-in window (hours-of-day 9..16, D-05). The same-day
contiguous ``[9-16]`` window an EV is plugged in at the workplace; unlike
``PLUGIN_WINDOW`` it does NOT wrap midnight, so its multi-session segmentation is
a simple same-day run (no evening-anchoring). Power-limiting + unserved-energy
accounting apply to this session in chronological order alongside the overnight
home session (D-04). The midday headroom that motivates it holds only marginally
(workplace ~33.57 kW vs overnight ~31.95 kW over the 14 coldest days, RESEARCH
Pitfall 1); the dominant lift is the extra available HOURS, not midday richness."""

AVAILABILITY_SCENARIOS = {
    "overnight": (PLUGIN_WINDOW,),
    "workplace": (PLUGIN_WINDOW, WORKPLACE_WINDOW),  # ← HEADLINE (D-07)
    "all_day": (tuple(range(24)),),
}
"""RETIRED (Phase 15 RETIRE-02, D-13): the power-limited availability-scenario sweep
is removed from the pipeline path (the controller replaces it). KEPT importable this
plan because the stage-5 ``apply_flexibility_contracts`` body still references it;
physically deleted in Plan 03 when that body is removed.

Ordered availability-scenario session sets for the three-scenario re-baseline
(D-06/D-07). Each value is a tuple of session windows (each window itself a tuple
of hour-of-day ints) the power-limited kernel iterates per day. ``"overnight"`` is
the 18→07 home-only baseline; ``"workplace"`` adds the daytime ``WORKPLACE_WINDOW``
and is the citable HEADLINE (D-07); ``"all_day"`` is the full-availability ceiling
(all 24 hours). Insertion order (overnight → workplace → all_day) is the report
emission order (Plan 02 wraps the per-penetration K-loop in this scenario loop)."""

TOLERANCE_UNSERVED_ENERGY_FRACTION_MAX_P95 = 0.01
"""RETIRED (Phase 15 RETIRE-02, D-13): the power-limited energy-fraction acceptability
gate; removed from the pipeline path (reliability-only gating). KEPT importable this
plan because the stage-5 ``apply_flexibility_contracts`` body still references it;
physically deleted in Plan 03 when that body is removed.

Power-limited flexible-leg acceptability gate (DAYTIME-02). The unserved-energy
fraction (energy undelivered at throttled power across ALL available session-hours,
divided by annual EV demand) must be strict-``<`` 1% at P95 for a swept point to
pass. This ADDS an aliased constant (RESEARCH Pitfall 4) reusing the value 0.01;
it does NOT rename or edit ``TOLERANCE_IRREDUCIBLE_LOST_FRACTION_MAX_P95`` (which
stays for the now-dormant valley-fill deferral path). Same value, different
meaning: "unserved energy" (power-limited) vs "irreducible lost" (deferral)."""

EXTENDED_PENETRATION_SWEEP = PENETRATION_SWEEP + (
    2.1,
    2.2,
    2.3,
    2.4,
    2.5,
    2.6,
    2.7,
    2.8,
    2.9,
    3.0,
    3.1,
    3.2,
    3.3,
    3.4,
    3.5,
    3.6,
    3.7,
    3.8,
    3.9,
    4.0,
    4.1,
    4.2,
    4.3,
    4.4,
    4.5,
    4.6,
    4.7,
    4.8,
    4.9,
    5.0,
)
"""RETIRED (Phase 15 RETIRE-02, D-13): the extended power-limited availability sweep
grid is removed from the pipeline path (the controller replaces the sweep). KEPT
importable this plan because the stage-5 ``apply_flexibility_contracts`` body still
references it; physically deleted in Plan 03 when that body is removed.

Extended EV-per-home penetration grid (0 → 5.0) for the power-limited
availability sweep (DAYTIME-04, Plan 02). APPEND-ONLY — the frozen
``PENETRATION_SWEEP`` (0 → 2.0, byte-frozen inside the locked Phase-10.1 block
above) is left UNEDITED; this constant is ``PENETRATION_SWEEP`` plus the additional
``2.1 → 5.0`` grid at the same 0.1 step. RATIONALE (RESEARCH Pitfall 2 / A2): under
power-limited natural charging the per-hour headroom (~27-34 kW) vastly exceeds the
aggregate EV draw until VERY high penetration, so the overnight-only unserved-energy
P95 stays below the 1% gate across the entire frozen 0 → 2.0 grid (flat-zero
saturation — the flexible count pins at the sweep top, an UNINFORMATIVE result). The
overnight unserved cliff crosses 1% near ~4.6 EV/home; extending to 5.0 lands the
cliff INSIDE the effective sweep so the gate is informative for every scenario. The
single re-point site is ``_availability_sweep``'s penetration loop in
``apply_flexibility_contracts.py`` (Plan 02); the frozen ``PENETRATION_SWEEP`` and
the golden config bytes are never mutated."""

# ─── Partial EV coincidence / diversity (260625-lgg, EV-COINCIDENCE-RECAL) ────
# APPEND-ONLY block below every locked constant above (everything through
# ``EXTENDED_PENETRATION_SWEEP`` is byte-frozen — do NOT edit any constant above).
# This knob replaces the implicit FULL-coincidence assumption baked into the
# four EV-demand consume sites (each built EV demand as ONE per-EV-unit shape
# scaled by the EV count → every EV charging the same shape at the same time, a
# model coincidence factor CF ≈ 1). The recalibration blends that coincident term
# with an INDEPENDENT term (``count`` independently-drawn per-EV days summed) at a
# literature-grounded mixing weight ``EV_COINCIDENCE_RHO`` so the model CF lands at
# the citable 0.55–0.7 band for ~7 cold-Québec dwellings.

EV_COINCIDENCE_RHO = _CONFIG["evCoincidenceRho"]
"""EV-aggregate coincidence mixing weight ``ρ`` in [0, 1] (EV-COINCIDENCE-RECAL).

The per-feeder EV aggregate at an integer EV ``count`` is the ρ-blend
``ρ · count · ev_unit  +  (1 − ρ) · independent_aggregate(count)`` where
``ev_unit`` is the existing ``(K, 8760)`` ``n_ev=1`` per-EV-unit realization shape
(the COINCIDENT shape — every EV identical and simultaneous) and
``independent_aggregate(count)`` is ``count`` INDEPENDENTLY-drawn per-EV days
summed (the diversified shape). ``ρ`` interpolates the two:

  - ``ρ = 1`` → the legacy FULL-coincidence edge: the blend is exactly
    ``count · ev_unit`` bit-for-bit (the diversified term is multiplied by 0).
    Model coincidence factor CF ≈ 1 (firm ~2–3, over-conservative).
  - ``ρ = 0`` → fully INDEPENDENT per-EV draws (maximally diversified); CF ≈ the
    diversity floor for the count (firm ~6).

CITABLE BASIS (Jonas, Daniels & Macht, *Energies* 2023, **16(4):1592**, >7000 CA
stations: residential charging peaks 15:00–24:00, EV coincidence **< 0.25 for
>50 EVs**; CALIBRATION.md [EV-3] / §3/§5: coincidence is **HIGHER for the few
dwellings on one transformer** and **RISES with cold ambient + lower charge
power** → CF ≈ 0.55–0.7 for 7 cold-Québec all-electric homes). Prototype
260625-lf4 mapped the citable CF to a LOW ρ at the diversified end; the GOVERNED
re-run (260625-lgg, non-worktree) calibrated the value against the FROZEN
governed gates (FIRM_PCONG_TOLERANCE strict-< etc.): ``ρ = 0.5`` lands the model
coincidence factor at **CF ≈ 0.71** (the firm-region 6-EV aggregate; the top of
the cited 0.55–0.7 band) AND the firm count at **6** (inside the ~5–6 target). A
LOWER ρ (≈0.2–0.4) over-diversifies the GOVERNED feeder (firm 7–9, above band);
a HIGHER ρ (≥0.6) pushes CF above the cited 0.7 ceiling (firm 5). ``ρ = 0.5`` is
the unique value satisfying BOTH the cited CF band AND the firm [5, 6] band on
this 71.25 kW / 7-home idx-62 unit. See ``_stochastic.blend_ev_aggregate`` for the
byte-stable per-count blend kernel."""

# ─── Cold-load pickup (CLPU) base uplift — DELETED (Phase 15 RETIRE-02, D-13) ──
# The CLPU base-uplift knobs (CLPU_PEAK / CLPU_TEMP_ONSET / CLPU_TEMP_FULL /
# CLPU_WINDOW, quick 260625-pwz) are physically REMOVED this plan: their sole
# consumer ``_stochastic.clpu_factor`` (and the annual ``tmy_base`` that applied
# it) was deleted in the same plan, and the re-anchored ``_twostage.compose_
# scenarios`` no longer applies CLPU (D-07: the base is now the emitted Q_design
# building mean, no CLPU lift). No live consumer remained, so the block is deleted
# outright rather than bannered.

# ─── Phase-13 (GEN-01..04): generative-MC design-day seam ────────────────
# APPEND-ONLY block below every locked constant above (everything through
# ``CLPU_WINDOW`` is byte-frozen — do NOT edit any constant above). These pin the
# governed ``_generators.py`` design-day Monte-Carlo kernel: the SDK building
# agent recalibrated to the Québec all-electric archetype + the project-local
# MDPI EV sampler, run over the binding cold design day to emit the idx-62
# transformer-load ensemble ``Q_real (K, n_steps)`` + the day-ahead forecast
# ``Q_design``. The operating point below is EMPIRICALLY LOCKED (2026-06-26
# throwaway probes ``exp_firmsweep.py`` / ``exp_genseam.py``); Phase 13 implements
# it byte-stably, it does NOT re-discover it. Reuses the locked ``SEED``,
# ``DTYPE``, ``ROUND_DECIMALS``, ``TMY_INPUT_PATH``, ``TRANSFORMER_KVA``,
# ``POWER_FACTOR``, ``CHARGER_MIX``, ``EV_KWH_*``, ``ARRIVAL_*``, ``PLUGIN_PROB``,
# ``SIGMA_DAILY``, ``SIGMA_HOURLY``, ``FIRM_PCONG_TOLERANCE`` (do NOT redefine them).

R_QUEBEC = _CONFIG["rQuebec"]
"""Recalibrated per-home thermal envelope resistance (°C/kW) of the SDK building
agent for the Québec all-electric archetype (GEN-02; the LOCKED operating point).

After ``make_buildings(n, seed)`` each ``Building.R`` is overridden to this value.
The SDK default (``R_MEAN ≈ 11``) under-loads the 7-home idx-62 unit to ~6.5 kW/
home / ~60% of the 71.25 kW rating; ``R = 7.0`` lands the EV-free design-day base
at **~8.4 kW/home coincident / ~82–87% of the 71.25 kW rating, firm=3**
(empirically verified at K=60 on the 1990-01-19 design day, probe
``exp_firmsweep.py``). CALIBRATION.md anchors: PMC ~13 kW baseboard, HQ
10–15 kW/dwelling. NOT the stale ``exp_genseam.py`` probe value (R=6.0); the
firm-sweep R=7.0 row is the locked grid point. NO CLPU (the heating recalibration
is the dominant lever; CLPU on top overshoots to ~117% / firm=0)."""

P_HEAT_QUEBEC = _CONFIG["pHeatQuebec"]
"""Recalibrated per-home baseboard heating capacity (kW) of the SDK building agent
(GEN-02; the LOCKED operating point).

After ``make_buildings`` each ``Building.p_heat_max`` is overridden to this value
(the SDK default ``P_HEAT_MAX_KW = 8.0`` under-sizes the all-electric Québec
baseboard). Anchored to the Québec all-electric archetype (~13 kW installed
baseboard nameplate; HQ 10–15 kW/dwelling), it pairs with ``R_QUEBEC = 7.0`` to
land the design-day base at the locked ~82–87% rating / firm=3 operating point."""

DESIGN_DAY_RES_MINUTES = _CONFIG["designDayResMinutes"]
"""Monte-Carlo aggregation resolution (minutes) for the design-day ensemble (GEN-01,
Claude's discretion per CONTEXT). ``select_peak_load_day`` returns the design day at
1-min native resolution; the building realization aggregates ``p_total_kw`` to this
step (the building hourly aggregate worked in the probes — ``exp_firmsweep.py`` /
``exp_genseam.py``). Default 60 (hourly → ``n_steps = 24``); a finer 5/15-min step
is an option if the K ensemble fidelity needs it, at higher MC cost."""

K_DESIGN = _CONFIG["kDesign"]
"""Design-day Monte-Carlo realization count (GEN-01, Claude's discretion).

Each realization re-seeds the SDK building agent + the temperature-forecast-error
offset from ``SEED + r`` (pinned). Chosen at the probe value ``K = 60`` — the count
at which the firm-region operating point (base ~82–87% rating, firm=3) was
empirically verified on the 1990-01-19 design day (``exp_firmsweep.py`` /
``exp_genseam.py``) — large enough for a stable p50 base-peak yet fast enough to run
the 7-home / 24-step kernel inside the unit-test budget (< 60 s). Part of the
reproducibility contract with ``SEED``; the Phase-14 firm pin re-uses this K."""

N_HOMES_FALLBACK = _CONFIG["nHomesFallback"]
"""Downstream-home count used by the design-day kernel when the topology cache's
selected-feeder home count is unavailable (e.g. cache-free unit tests). Option B
(2026-07-06): the twin's LV transformers are now PHYSICALLY 75 kVA, the clustering
lands ~6 homes/unit, and ``select_feeder`` picks an exact ``TARGET_HOMES = 6``
unit (idx-10 in the regenerated twin; the pre-option-B twin's closest unit was
idx-62 → 7). The governed stage passes the cache value, the unit tests pass this
fallback so they stay cache-free (CONTEXT: the gitignored cache lives only in the
main tree)."""

DESIGN_DAY_EV_MAX = _CONFIG["designDayEvMax"]
"""Nested-EV pool ceiling for the design-day MC sweep (GEN-03). ``ev_nested_pool``
returns a ``(DESIGN_DAY_EV_MAX + 1, n_steps)`` cumulative pool (row n = the first n
EVs) so the Phase-14 congestion sweep can overlay any EV count up to this ceiling.
Sized comfortably above the expected firm count (firm=3 at the locked operating
point; the EV sweep crosses the rating well below 18) per the probe
``exp_genseam.py`` (``EV_MAX = 18``)."""

# ─── Phase-15 (CTRL-02, D-03/D-04/D-11): out-of-sample validation knobs ──────
# APPEND-ONLY block below the Phase-13 design-day seam (everything above is
# byte-frozen — do NOT edit any constant above). These pin the controller's
# out-of-sample reliability harness (Plan 03): the reserve r_t is planned on a
# Q_design-anchored forecast ensemble drawn from the K_DESIGN plan-seed block,
# then validated on a FRESH DISJOINT Q_real ensemble drawn at controller time
# with a seed block disjoint from the plan set, plus an adversarial colder-Q_real
# degradation test. All three knobs are PINNED for Phase-17 byte-stability.

OOS_N = _CONFIG["oosN"]
"""Out-of-sample validation ensemble size N (D-04). Symmetric with ``K_DESIGN``
(N = K = 60): the realized ``P(overload after activation)`` is evaluated on N
independent ``Q_real`` realizations drawn at controller time. A larger N (200–500)
for a tighter ε-tail estimate is a later precision option (D-04); pinned at 60
here for the symmetric plan/validation budget."""

OOS_SEED_OFFSET = _CONFIG["oosSeedOffset"]
"""Disjoint validation seed-block offset (D-03). The out-of-sample ``Q_real``
ensemble is drawn via ``make_design_day_ensemble(seed=SEED + OOS_SEED_OFFSET)`` so
every per-realization stream (building ``seed + r``, EV pool ``seed + 7919·r``,
forecast ``seed + 1``) is disjoint from the ``SEED`` plan/forecast block: 10000 ≫
K = 60 and avoids the ``7919·r`` EV-pool stride collisions in range (RESEARCH A1),
making the validation draws genuinely unseen by the plan."""

ADVERSARIAL_DELTA_C = -5.0
"""Pinned deterministic colder-``Q_real`` temperature offset (°C) for the
adversarial degradation test (D-11). ``building_realization(..., t_offset=
ADVERSARIAL_DELTA_C)`` regenerates the validation ``Q_real`` ensemble 5 °C colder;
the realized ``P(overload)`` is asserted to DEGRADE above ε — quantified and
REPORTED, never gated to fail (the in-band realized check is the non-adversarial
assertion)."""

ADV_SEED_OFFSET = _CONFIG["advSeedOffset"]
"""Disjoint adversarial seed-block offset (RESEARCH A4). The adversarial colder
``Q_real`` ensemble is drawn from ``SEED + ADV_SEED_OFFSET + r`` — a third disjoint
block distinct from both ``SEED`` (plan) and ``SEED + OOS_SEED_OFFSET`` (the
in-band validation set) — so the three ensembles stay byte-independent."""

# ─── Phase-16 (ECON-02 / D-16-4): non-wires economics governed constants ─────
# APPEND-ONLY block below the Phase-15 out-of-sample knobs (everything above is
# byte-frozen — do NOT edit any constant above; in particular do NOT redefine
# SEED, DTYPE, ROUND_DECIMALS, K_DESIGN, TRANSFORMER_KVA or POWER_FACTOR — the
# config warns against redefinition). These promote the manuscript's previously
# "illustrative" non-wires economics prices/CAPEX/discount/life/adoption ramp/
# deferral-feasibility constants to GOVERNED constants with labelled provenance.
# The ECON-01 kernel (`_economics.py`, Plan 02) and the new economics stage
# (Plan 03) import these. Each value is a plain float/int literal — the CRF and
# annualized-reinforcement figures are kernel-DERIVED (Plan 02), not computed
# here. Provenance: manuscripts/ev_hosting_flex/scripts/figures/
# nonwires_economics.py and breakeven_nonwires.py (the two scripts agree on the
# shared prices C_R_BASE/C_A/CAPEX_UPGRADE/DISCOUNT/LIFE_YEARS/TOL_FRACTION).

C_R_BASE = _CONFIG["cRBase"]
"""Baseline reservation price, $/kW per reservation-day (ECON-02 / D-16-4).
Promotes the manuscript's previously illustrative per-reservation availability fee
to a governed constant. Provenance: ``nonwires_economics.py`` ``C_R_BASE`` and
``breakeven_nonwires.py`` ``C_R_EVENT`` (both = 2.0). Scales the reported cost
frontier; does NOT move the hosting headline (distinct from the ``C_RESERVE``
two-stage frontier-scaling price above)."""

C_A = _CONFIG["cA"]
"""Activation price, $/kWh shifted/activated in real time (ECON-02 / D-16-4).
Promotes the manuscript's illustrative DR-like energy-shift price to a governed
constant. Provenance: ``nonwires_economics.py`` / ``breakeven_nonwires.py`` ``C_A``
(both = 0.30)."""

CAPEX_UPGRADE = _CONFIG["capexUpgrade"]
"""Reinforcement capital cost, $ (ECON-02 / D-16-4). Installed cost to replace the
50 → 100 kVA residential transformer (HQ residential). The annualized
capital-recovery figure (CRF · CAPEX) is kernel-derived in Plan 02, not here.
Provenance: ``nonwires_economics.py`` and ``breakeven_nonwires.py``
``CAPEX_UPGRADE`` (both = 8000.0)."""

DISCOUNT_RATE = _CONFIG["discountRate"]
"""Annual discount rate for the capital-recovery factor (ECON-02 / D-16-4). Named
``DISCOUNT_RATE`` (NOT ``DISCOUNT``) so it is unambiguous and self-documenting; the
Plan-02 CRF formula consumes ``DISCOUNT_RATE``. Provenance: ``nonwires_economics.py``
and ``breakeven_nonwires.py`` ``DISCOUNT`` (both = 0.05)."""

LIFE_YEARS = _CONFIG["lifeYears"]
"""Asset life in years for the capital-recovery factor (ECON-02 / D-16-4).
Provenance: ``nonwires_economics.py`` and ``breakeven_nonwires.py`` ``LIFE_YEARS``
(both = 30)."""

P0_ADOPT = _CONFIG["p0Adopt"]
"""Today's EV penetration, EV/home, for the adoption ramp (ECON-02 / D-16-4).
Provenance: ``nonwires_economics.py`` ``P0_ADOPT`` (= 0.5)."""

PMAX_ADOPT = _CONFIG["pmaxAdopt"]
"""Adoption target, EV/home (ECON-02 / D-16-4). The terminal penetration the
adoption ramp climbs toward. Provenance: ``nonwires_economics.py`` ``PMAX_ADOPT``
(= 4.0)."""

ADOPT_YEARS_BASE = _CONFIG["adoptYearsBase"]
"""Baseline years-to-``PMAX_ADOPT`` for the deferral-NPV headline (ECON-02 /
D-16-4). Provenance: ``nonwires_economics.py`` ``ADOPT_YEARS_BASE`` (= 15)."""

TOL_FRACTION = _CONFIG["tolFraction"]
"""Deferral feasibility ceiling = undeliverable / EV-energy fraction (ECON-02 /
D-16-4). The annual-curtailed-over-EV-energy ratio above which the deferral is
declared infeasible. Provenance: ``nonwires_economics.py`` and
``breakeven_nonwires.py`` ``TOL_FRACTION`` (both = 0.05)."""

DEFERRAL_ENROLLMENT_FRACTION = _CONFIG["deferralEnrollmentFraction"]
"""Fraction of EVs enrolled in managed/deferred charging — the GOVERNING flex
headline knob (ECON-02 / D-16-4, D-16-2a). The single binding lever on the
deferral-model flex count. Provenance: the manuscript's conservative +100% / flex 6
end, reconciled with the Phase-16 sensitivity spike (D-16-2a): 25–30% → 6, 50% → 8,
60% → 13, ≥70% → pool-capped. Pinned at the 0.30 conservative headline value."""

DEFERRAL_PLUGIN_WINDOW = tuple(_CONFIG["deferralPluginWindow"])
"""Overnight plug-in / availability window, hour-of-day (ECON-02 / D-16-4,
D-16-1/D-16-2a). Arrival ~18:00 → departure ~07:00 (14 hours). Revives the
Phase-15-retired ``PLUGIN_WINDOW`` for the deferral model; governed for faithfulness
but NON-BINDING per the Phase-16 spike (the overnight window comfortably accommodates
the shiftable EV energy). Provenance: the manuscript deferral model's overnight
availability assumption."""

DEFERRAL_CHARGER_KW_CEILING = _CONFIG["deferralChargerKwCeiling"]
"""Per-charger power ceiling, kW (Level-2 EVSE) (ECON-02 / D-16-4). Governed for
completeness but NON-BINDING per the Phase-16 spike — 3.7–11 kW all give the same
deferral count because the overnight window, not the charger power, is the binding
constraint. Provenance: standard Level-2 residential EVSE rating."""

# ─── AC power-flow validation (2026-07-06, validate_powerflow stage) ─────────
# APPEND-ONLY block below the Phase-16 economics constants (everything above is
# byte-frozen — do NOT edit any constant above). These pin the network-level AC
# validation layer added after the option-B physical twin (75 kVA / 240 V
# secondary): a deterministic design-day power flow per EV scenario, emitting
# governed bus-voltage / line-loading / transformer-loading artifacts.

SLACK_VM_PU = _CONFIG["slackVmPu"]
"""Substation slack (LTC-regulated 25 kV bus) voltage setpoint in pu for the AC
validation power flows. HQ substation LTCs hold distribution feeders slightly
above nominal; empirically verified on this twin (2026-07-06 session probes):
1.03 pu leaves 2/3775 LV buses below the CSA C235 110 V normal-range floor at
the ADMD winter peak, 1.05 pu leaves none — 1.04 is the mid setpoint. Consumed
only by the validate_powerflow stage; the kW-proxy congestion chain (stages
3-6) never reads it."""

VOLTAGE_LIMITS_PU = _CONFIG["voltageLimitsPu"]
"""CSA C235 service-voltage bands on the 120 V base, in pu (normal range
110-125 V -> 0.917-1.042; extreme low 106 V -> 0.883). The violation counters in
the validate_powerflow stage classify LV bus voltages against these bands."""

NETWORK_PENETRATION_SCENARIOS = tuple(_CONFIG["networkPenetrationScenarios"])
"""Network-wide uniform EV adoption levels (EV/home) for the AC validation's
"before vs after" scenario family. Every one of the 3235 homes receives the
diversified coincident EV draw ``penetration x EV_UNIT_KW x DIVERSITY_FACTOR``
(2.52 kW/EV) inside ``CHARGING_WINDOW``; 0.0 is the pre-EV reference network."""

# ─── STUDY-B annual migration (2026-07-06, Option A — D-B1..D-B7) ────────────
# APPEND-ONLY block below the AC power-flow validation constants (everything
# above is byte-frozen — do NOT edit any constant above). These pin the study-B
# annual model the pipeline is being re-founded on (see docs/superpowers/specs/
# 2026-07-06-ev-hosting-flex-study-b-annual-migration.md): pure Monte-Carlo over
# the full TMY year with ONLY the SDK stochastic generators, cold-coupled EVs,
# and the curtailment-with-notice mechanism. Provenance: manuscripts/
# ev_hosting_flex/scripts/study_b/{generate_sdk_base,curtailment_study_refined}.py
# (the authoritative sandbox). Reuses the locked SEED, DTYPE, ROUND_DECIMALS,
# TRANSFORMER_KVA, POWER_FACTOR, TMY_INPUT_PATH, CHARGER_MIX, CAPEX_UPGRADE,
# DISCOUNT_RATE, LIFE_YEARS (do NOT redefine them).

# ─── Heating controller ────────────────────────────────────────────────
# Per-zone latching thermostats (SDK ``control="hysteresis"``). The historical
# "proportional" law glides where a real dwelling steps, so its homes arrive
# pre-diversified and an aggregate of a FEW of them comes out too smooth --
# which is exactly the regime this study works in (6-home pole transformers).
#
# Measured on the full TMY year against the Hydro-Québec all-electric subset
# (n=215), peak kW per home at 6 dwellings:
#     real 11.82 | proportional 10.23 (-13.4%) | hysteresis 11.19 (-5.3%)
# A negative bias understates base load and therefore OVERSTATES EV hosting
# capacity. Annual energy is unchanged by the swap (29.9 -> 30.0 MWh/home), so
# the R_STUDY_B energy calibration below stands as-is.
#
# Residual bias is -5.3%, not zero: the base remains mildly optimistic.
HEATING_CONTROL = _CONFIG["heatingControl"]

R_STUDY_B = _CONFIG["rStudyB"]
"""Per-home thermal envelope resistance (deg C/kW), study-B all-electric base.

RE-BASED 2026-07-14 (spec realistic-building-base-dhw): 5.0 -> 7.5. The old 5.0
was reverse-engineered to hit the HQ winter peak (11.4 kW/home) with the bare RC
envelope, which inflated annual energy to ~39 MWh/home (~1.8x the SDK-native
20-22; QC all-electric typical 25-30). R=7.5 gives energy-realistic heating
(~18 MWh); the explicit DHW tank (`dhw_tank_annual`) + `BG_SCALE` restore the
coincident peak to the HQ 10-15 kW band WITHOUT the energy inflation. Final value
fixed by calibrate_base.py. Supersedes the peak-calibrated 5.0."""

K_ANNUAL = _CONFIG["kAnnual"]
"""Annual SDK base realization count (D-B2). Study-B faithful default 1 (the
within-year day-to-day thermostat/AR(1)/weather variation is the sampling
axis); the plumbing accepts K > 1 (seeds ``SEED + r``) for ensemble tails."""

ANNUAL_RES_MINUTES = _CONFIG["annualResMinutes"]
"""Temporal resolution (minutes) of the annual kW chain (2026-07-07 granularity
finding). Hourly means UNDERSTATE the sub-hourly coincidence of the few 13 kW
baseboard thermostats + the discrete 7.2-11.5 kW EV step: the Jan-Mar 1-min
probe showed the P95 cold-evening loading rising ~7 points (100% -> 107% at
3 EVs) and firm dropping ~1 EV between 60- and 15-min aggregation, with
sustained (>15 min) exceedances that a pole transformer's winding time constant
(~5-15 min) genuinely feels. 15 min is the utility demand-metering interval and
the dulce spot: finer than 15 adds only ~2-4 P95 points and enters the regime
the transformer's thermal inertia legitimately filters. The SDK agent already
simulates at 1-min, so the finer base aggregation is FREE; the EV sampler
allocates sessions minute-exact into 15-min bins. The AC validation layer stays
HOURLY (aggregated from this) — 96-step power flows would ~4x a validation cost
for no gate value. Arrays are ``(K, N_DAYS * 24*60/ANNUAL_RES_MINUTES)`` = 35040
steps at 15 min; energy is ``sum(kW_per_step) * ANNUAL_RES_MINUTES/60``."""

FC_SIGMAS = tuple(_CONFIG["fcSigmas"])
"""Day-ahead temperature-forecast error sigmas (°C) for the notice-quality
forecast bases (D-B3). Provenance: ``generate_sdk_base.py`` ``FC_SIGMAS``."""

SEED_FC_OFFSETS = _CONFIG["seedFcOffsets"]
"""RNG seed of the per-day N(0, σ) forecast-offset draws (D-B3). Provenance:
``generate_sdk_base.py`` ``rng = default_rng(7)``."""

POOL_MAX_ANNUAL = _CONFIG["poolMaxAnnual"]
"""Nested annual EV pool ceiling (D-B4). One governed pool
``(POOL_MAX_ANNUAL, 8760)`` drawn from ``default_rng(SEED)``; every sweep
(hosting, enrollment, economics) uses row prefixes. DEVIATION from study_b's
two ad-hoc pools (seeds 1 and 8 EVs / 7 and 9 EVs): one pinned pool.

RAISED 12 -> 16 on 2026-07-30. Under the temperature-dependent rating the firm
count reaches 12 (2.00 EV/home) on the 6-home unit, i.e. exactly the old
ceiling, so the stage could not evaluate firm+1 and reported `None` for the
crossing. Verified with a 40-EV pool that 12 is the GENUINE limit and not a
pool artefact -- but the ceiling must sit above it for the boundary to be
demonstrable rather than assumed. 16 = 2.67 EV/home, comfortably above both the
firm limit and the 1.32 EV/home Québec saturation."""

E_TREF_C = _CONFIG["eTrefC"]
"""Cold-intensity reference temperature (°C) (D-B4): ``cp = max(0, E_TREF_C −
Tday)`` drives BOTH the session-energy and plug-in cold penalties. Provenance:
``curtailment_study_refined.py`` ``E_TREF``."""

EV_KWH_BASE = _CONFIG["evKwhBase"]
"""Mild-day median session energy (kWh) (D-B4). Provenance: ``E_BASE = 8.0``
(consistent with the Phase-10.1 ``EV_KWH_MEDIAN``)."""

EV_KWH_KCOLD = _CONFIG["evKwhKcold"]
"""Session-energy cold slope (per °C of cold intensity) (D-B4): median =
``EV_KWH_BASE·(1 + EV_KWH_KCOLD·cp)`` → +50 % at −25 °C (cp = 40). Cold cuts EV
range ~40–50 % so sessions deepen exactly on the critical evenings. Provenance:
``E_KCOLD = 0.0125``."""

PLUGIN_BASE = _CONFIG["pluginBase"]
"""Mild-day plug-in probability (D-B4). Provenance: ``PLUG_BASE = 0.60``."""

PLUGIN_KCOLD = _CONFIG["pluginKcold"]
"""Plug-in probability cold slope (per °C of cold intensity) (D-B4):
``min(PLUGIN_MAX, PLUGIN_BASE + PLUGIN_KCOLD·cp)`` — range anxiety +
preconditioning + everyone-home raise evening plug-ins with cold. Provenance:
``PLUG_KCOLD = 0.006``."""

PLUGIN_MAX = _CONFIG["pluginMax"]
"""Plug-in probability ceiling on the coldest days (D-B4). Provenance:
``PLUG_MAX = 0.85``."""

EV_SIGMA_LOG = _CONFIG["evSigmaLog"]
"""Lognormal sigma (log-space) of the session energy (D-B4; same value as the
Phase-10.1 ``EV_KWH_SIGMA``, restated here as the annual-path contract)."""

ARRIVAL_MEAN_ANNUAL_H = _CONFIG["arrivalMeanAnnualH"]
"""Evening arrival mean hour (D-B4). Provenance: ``rng.normal(18.0, 1.5)``."""

ARRIVAL_STD_ANNUAL_H = _CONFIG["arrivalStdAnnualH"]
"""Evening arrival std (hours) (D-B4)."""

ARRIVAL_CLIP_ANNUAL = tuple(_CONFIG["arrivalClipAnnual"])
"""Arrival clip window (hours) (D-B4). Provenance: ``np.clip(s, 16.0, 22.0)``."""

COLD_DAY_TMEAN_C = _CONFIG["coldDayTmeanC"]
"""Cold-day classifier (D-B5): days with mean temperature below this (°C) form
the cold-day set of the firm P95-evening rule. Provenance:
``curtailment_study_refined.py`` ``tday < 5.0``."""

EVENING_WINDOW_ANNUAL = tuple(_CONFIG["eveningWindowAnnual"])
"""Evening hours-of-day window (end-exclusive) of the firm rule (D-B5): firm =
largest n with ``P95(cold-day max evening loading) ≤ 100 %``. Provenance:
``[:, 16:23].max(1)``."""

FIRM_P95_LIMIT_PERCENT = _CONFIG["firmP95LimitPercent"]
"""Firm-rule loading threshold (%) on the P95 cold-day evening peak (D-B5)."""

C_AVAIL_EV_YR = _CONFIG["cAvailEvYr"]
"""Curtailment-contract availability payment ($/EV/yr) (D-B6). Provenance:
``C_AVAIL = 80.0``."""

C_A_CURTAIL = _CONFIG["cACurtail"]
"""Curtailment-contract activation price ($/kWh curtailed) (D-B6). Provenance:
``curtailment_study_refined.py`` ``C_A = 0.5`` (~5× retail; distinct from the
governed deferral ``C_A = 0.30``)."""

C_RETAIL_KWH = _CONFIG["cRetailKwh"]
"""Retail energy value ($/kWh) of the foregone charging energy — the household
floor of the zone-of-agreement panel (D-B6). Provenance: ``C_RETAIL = 0.10``."""

# ─── Network-wide transformer sizing (2026-07-07, AC validation realism) ─────
# APPEND-ONLY block. Quebec/HQ LV distribution sizes each pole transformer to
# its connected load on a standard single-phase kVA ladder (NOT a uniform
# fleet), and rates it dynamically for the cold winter ambient (IEEE C57.91),
# consistent with the config's MV/HV transformer. The AC validation stage uses
# these to give each of the 540 LV transformers its OWN load-matched rating so
# the "before vs after EVs" network picture is physical (the uniform 75 kVA
# fleet left 213/540 transformers overloaded at design cold with zero EVs — a
# real under-sizing artifact of the geographic KMeans clustering, not physics).
# The GOVERNED study feeder (idx-10, 6 homes) lands at 75 kVA by this rule, so
# the firm/flexible headlines are unaffected; these constants touch ONLY the
# validate_powerflow network family.

TRANSFORMER_KVA_LADDER = tuple(_CONFIG["transformerKvaLadder"])
"""Standard single-phase distribution-transformer sizes (kVA) HQ picks from.
Each LV transformer is sized to the smallest ladder rung whose usable kW
(``kVA × POWER_FACTOR``) covers its SDK design-cold aggregate load; a 6-home
cluster lands at 75 kVA (matching the governed unit), a 12-home at 167 kVA."""

LV_DYNAMIC_RATING_K = _CONFIG["lvDynamicRatingK"]
"""Cold-ambient dynamic thermal rating factor for the LV transformers at the
design cold (IEEE C57.91). A transformer runs cooler in a −20 °C ambient and can
carry more than nameplate without exceeding its 110 °C hot-spot limit.

VERIFIED (2026-07-08) against the IEEE C57.91 steady-state hot-spot model: at
−22.5 °C, keeping the hot-spot at the 110 °C normal-life limit gives K = 1.37
with base parameters (top-oil rise 55 °C, hot-spot-over-oil 25 °C, R = 6,
oil/winding exponents n = 0.9 / m = 0.8), and K = 1.31–1.41 across the plausible
exponent range (n = m = 0.8 → 1.405). So 1.40 is at the OPTIMISTIC end (~+2 % vs
the 1.37 base case) but inside the physical band. Cross-checked against
Hydro-Québec practice — HQ actively dynamic-thermal-rates transformers for
winter overload (Rajotte & Picher, "Experience with transformer loading tests
and direct temperature measurements in laboratory and in service", CIGRE 2018,
paper A2-110, SC A2 PS1). Their direct hot-spot measurements exist BECAUSE the
simplified model has cold-weather uncertainties (oil viscosity, hot-spot factor)
— so a fixed K is a documented simplification. SAFE because it is REPORTING-ONLY
(the dynamic overload count, loading > 100 × K = 140 %); the GOVERNED
firm/flexible gate stays on the conservative STATIC rating (``TRANSFORMER_KVA ×
POWER_FACTOR``), so the ~2 % optimism never touches the headlines."""

LV_LINE_UTIL_TARGET = _CONFIG["lvLineUtilTarget"]
"""Design-cold thermal utilization target the LV secondary conductors are sized
to (2026-07-07 network verification). Like the transformers, the SDK
``load_aware`` line sizing used the clustering's soft coincident model
(10 kW/home diversified), but the SDK design-cold load is ~11 kW/home with
near-zero diversity — so the LV conductors are undersized for the Québec
all-electric winter peak, causing pre-EV line overloads on the larger clusters.
The validate_powerflow stage upsizes each LV line so its design-cold current
sits at this fraction of the (re-sized) conductor ampacity. GOVERNED chain
untouched (in-memory, AC layer only)."""

LV_LINE_VDROP_BUDGET_PU = _CONFIG["lvLineVdropBudgetPu"]
"""Per-conductor design-cold voltage-drop budget (pu) the LV lines are ALSO
sized to (2026-07-07 verification). Real LV design sizes conductors for BOTH
thermal ampacity AND voltage drop — on loaded runs the voltage constraint
usually binds. Sizing only for thermal (``LV_LINE_UTIL_TARGET``) fixed the line
overloads but left the LV secondary undervoltage (the drop is spread over many
lines within their thermal limit). Each LV line is upsized so its design-cold
per-line drop ``√3·I·(R·pf + X·sinφ)·length / Vn`` ≤ this budget; the binding
scale is ``max(thermal, voltage)``. NOTE (documented modeling boundary): this
sizes the LV SECONDARY only — the residual deep-feeder undervoltage (~0.91 pu)
is the inherent drop of the long 25 kV MV feeder, which a real network holds
with the substation LTC / line regulators, not conductor gauge."""

# ─── Network characterization (2026-07-08): losses, substation, headroom ─────
# APPEND-ONLY. Constants for the network-characterization analysis stage
# (losses / substation constraint / per-transformer hosting headroom) over the
# design-day full-net power flows, before the economic analysis.

SUBSTATION_DYNAMIC_RATING_K = _CONFIG["substationDynamicRatingK"]
"""Cold-ambient IEEE C57.91 dynamic rating factor of the HV/MV substation
transformers. Provenance: the config ``transformers.mv_hv`` note ("K(−22.5 °C)=
1.41"). VERIFIED (2026-07-08) — same C57.91 hot-spot check as
``LV_DYNAMIC_RATING_K``: the rigorous value at −22.5 °C / 110 °C hot-spot is
1.37 (base) to 1.41 (n = m = 0.8), so 1.41 is at the optimistic edge but within
the physical band; cross-checked vs HQ dynamic-thermal-rating practice (Rajotte
& Picher, CIGRE 2018 A2-110). The characterization reports the substation peak
loading against BOTH its static nameplate (100 %) and this dynamic limit
(141 %). After the HQ load-matched resizing the substation sits ~82 % at 0 EV
and stays within the dynamic limit across the sweep — the FEEDERS bind first,
not the substation (this factor is reporting-only, never a governed gate)."""

HEADROOM_PENETRATION_GRID = tuple(_CONFIG["headroomPenetrationGrid"])
"""EV-per-home penetration grid swept for the loss / substation / headroom
curves (D). Each point is a 24-hour design-day full-net power flow; per-element
peak loading is interpolated across the grid to find the penetration at which
each transformer first crosses its limit (the hosting-headroom map)."""

# ─── Substation transformer sizing (2026-07-08, HQ-realistic per verification) ─
# APPEND-ONLY. The bibliographic verification (Hydro-Québec docs) found real HQ
# 120-25 kV distribution substation transformers are 33-140 MVA (2-4 per
# substation, N-1), while the twin's synthetic builder placed 2 x 15 MVA — under
# the ~35 MW all-electric coincident design-cold load of the 3235-home area, so
# the more-loaded unit sat at ~140% (its cold dynamic limit) with ZERO EVs. The
# inter-cluster diversity at design cold is ~0 (all-electric heating is
# weather-driven and coincident — verified factor 0.997), so that loading is
# real, not an artifact. Size each substation transformer to ITS downstream
# design-cold load, mirroring the LV-fleet philosophy.

SUBSTATION_MVA_LADDER = tuple(_CONFIG["substationMvaLadder"])
"""Standard HQ-realistic 120/25 kV substation-transformer sizes (MVA) the twin's
substation transformers are matched to. Provenance: HQ distribution substations
use 33-140 MVA units (33.3 on 120-12 kV, 50-100 in growth zones, 140 on
315-25 kV); for the ~1600-home half each of our transformers serves, the lower
ladder rungs (25-33.3 MVA) are the realistic match."""

SUBSTATION_UTIL_TARGET = _CONFIG["substationUtilTarget"]
"""Design-cold utilization target the substation transformers are sized to (like
``LV_LINE_UTIL_TARGET`` and the LV-transformer 0.8 margin). Each substation
transformer takes the smallest MVA ladder rung whose usable MW
(``MVA × POWER_FACTOR``) covers its downstream coincident design-cold load /
this target, landing it ~85% loaded before EVs so the EV sweep pushes it toward
its limit cleanly. NOTE: this sizes for NORMAL operation; HQ's N-1 criterion
(each unit carries the full load on contingency) would require ~2x — a documented
reliability margin beyond this study's normal-operation hosting scope."""

# ─── Substation N-1 reliability configuration (2026-07-08, HQ-realistic) ─────
# APPEND-ONLY. The substation-sizing verification (Hydro-Québec docs + utility
# planning practice) established that substations are sized by the N-1
# contingency criterion — not a normal-operation utilization target: the
# substation must still serve the load with ONE transformer out. HQ favours
# THREE 120/25 kV transformers per substation (provision for a 4th). This block
# reconfigures the twin's 2-transformer substation into a 3-transformer N-1
# substation with a common (tied) MV bus, each transformer sized so the (N-1)
# remaining units carry the full area load.

SUBSTATION_N_TRANSFORMERS = _CONFIG["substationNTransformers"]
"""Number of identical parallel 120/25 kV substation transformers on a common
(tied) MV bus. The STANDARD/typical HQ distribution-substation configuration is
TWO identical redundant units adhering to N-1 (each carries the full load on a
single-transformer contingency using its emergency rating); 3-4 units are used
only in large/high-growth substations, not at this ~35 MW / 3235-home scale. The
twin ships exactly 2 (separate MV halves); the validate_powerflow reconfiguration
ties their MV buses onto a common node so they parallel-share and the N-1
contingency is realizable — no unit is added at N = 2."""

SUBSTATION_EMERGENCY_FACTOR = _CONFIG["substationEmergencyFactor"]
"""Short-term emergency loading factor for the substation transformers on an N-1
contingency (utility practice: 1.5x nameplate for units < 100 MVA, 1.3x for
> 100 MVA). The firm-capacity metric reports the load the substation can serve
with one transformer out at BOTH the normal rating ((N-1) x nameplate) and this
emergency rating ((N-1) x nameplate x factor)."""

SUBSTATION_N1_CONTINGENCY_TARGET = _CONFIG["substationN1ContingencyTarget"]
"""Target loading (per-unit of nameplate) of the (N-1) remaining transformers on
a single-unit contingency, used to SIZE the bank: each unit is the smallest
``SUBSTATION_MVA_LADDER`` rung with ``nameplate >= total_load_MVA / ((N-1) x
SUBSTATION_N1_CONTINGENCY_TARGET)``. 1.20 is the classic distribution-substation
N-1 design point — comfortably within the 1.5 emergency capability, equivalent
to the "peak load < 60 % of total installed capacity" rule for 2 transformers.
For the ~37 MVA area with N = 2 this lands each unit at 33.3 MVA (a real HQ
size): ~56 % loaded normally, ~112 % on an N-1 contingency."""

# ─── Clustered EV adoption (Study 3B, 2026-07-08) ────────────────────────────
# APPEND-ONLY. Non-uniform ("clustered") EV adoption over the ~540 last-mile
# transformers at a FIXED total fleet: per-transformer adoption rate is drawn
# from a mean-preserving lognormal so the fleet is invariant while dispersion
# (Gini/CoV) grows. Sweeps mean adoption (CLUSTER_MU_GRID) and dispersion
# (CLUSTER_DISPERSION_GRID); CLUSTER_MC_DRAWS realizations per level give bands.
CLUSTER_MEAN_RATE = _CONFIG["clusterMeanRate"]
"""Fixed mean adoption (EV/home) for the penalty-vs-Gini axis (Part 1, eje A)."""

CLUSTER_MU_GRID = tuple(_CONFIG["clusterMuGrid"])
"""Mean-adoption grid (EV/home) swept for the first-reinforcement axis (eje B):
the mean penetration at which the WORST transformer first crosses 100%."""

CLUSTER_DISPERSION_GRID = tuple(_CONFIG["clusterDispersionGrid"])
"""Lognormal dispersion levels (sigma). 0.0 = uniform (a_t == mu exactly);
higher = more clustered. The Gini/CoV of the adoption vector rises with it."""

CLUSTER_MC_DRAWS = _CONFIG["clusterMcDraws"]
"""Monte-Carlo draws of the adoption vector per (dispersion, mu) level; the
per-transformer loading is reduced across draws (median) for stable curves."""

CLUSTER_MAX_RATE = _CONFIG["clusterMaxRate"]
"""Physical cap on per-transformer adoption (EV/home) after the mean-preserving
draw, guarding absurd tail values; realized fleet drift from the cap is
reported. Chosen well above CLUSTER_MU_GRID[-1] so it rarely binds."""

# ─── Flexibility incentive / climate axis (Study 1A, 2026-07-08) ─────────────
# APPEND-ONLY. The optimal flexibility incentive migrates with climate: on warm
# days a valley exists so a cheap ToU/valley-fill SHIFT discount hosts EVs; on
# cold all-electric days there is no overnight valley (base 67-89% around the
# clock) so only a CURTAILMENT payment relieves the feeder. The WTA curve is an
# ILLUSTRATIVE behavioural assumption (like the deck's enrollment lever) — the
# crossover TEMPERATURE is robust (shift is physically infeasible in the cold
# regardless of WTA); the subsidy DOLLARS are illustrative.
CLIMATE_BIN_EDGES = (-25.0, -20.0, -15.0, -10.0, -5.0, 0.0, 5.0)
"""Daily-mean-temperature bin edges (°C) for the climate axis; days are grouped
into the half-open bins [edge_i, edge_{i+1})."""

HOSTING_TARGET_EV_PER_HOME = _CONFIG["hostingTargetEvPerHome"]
"""Fleet to host on the 6-home feeder (× 6 = N EVs). Chosen in the binding
range: uncontrolled must exceed 100% P95 in the cold bins so flexibility is
actually needed (the stage reports if it is not binding in a bin)."""

WTA_SHIFT_MEDIAN = _CONFIG["wtaShiftMedian"]
"""Median willingness-to-accept ($/EV·yr) to enrol in a SHIFT program (low —
overnight smart-charging is little inconvenience). Lognormal location."""

WTA_SHIFT_SIGMA = _CONFIG["wtaShiftSigma"]
"""Lognormal sigma (spread) of the SHIFT WTA distribution."""

WTA_CURTAIL_MEDIAN = _CONFIG["wtaCurtailMedian"]
"""Median willingness-to-accept ($/EV·yr) to enrol in a CURTAILMENT program
(higher — giving up / delaying charge has real disutility). Lognormal location."""

WTA_CURTAIL_SIGMA = _CONFIG["wtaCurtailSigma"]
"""Lognormal sigma (spread) of the CURTAILMENT WTA distribution."""

# ─── Study 1A reframe: penetration crossover (2026-07-09) ────────────────────
# APPEND-ONLY. Rigorous optimal valley-fill shift turned out FEASIBLE even in
# the cold at 2 EV/home: the all-electric base is high (67-89%) but not at 100%
# all day, so the DISTRIBUTED daily headroom (~353 kWh on the coldest day)
# absorbs the fleet when spread optimally into the shallow evening/overnight dip.
# The binding variable is therefore the per-bin SHIFT-HOSTING CEILING (the
# EV/home at which optimal shift exhausts the daily headroom); it falls with cold
# (less headroom). Beyond the ceiling, curtailment is required. To resolve that
# ceiling the 12-EV pool is TILED, and the incentive crossover is evaluated at a
# high-adoption target above the cold ceiling.
POOL_TILES = _CONFIG["poolTiles"]
"""Integer tiling of the 12-EV pool for the penetration sweep (× 12 = max EVs;
4 → 48 EVs = 8 EV/home on the 6-home feeder). Homogeneous-fleet penetration."""

INCENTIVE_TARGET_EV_PER_HOME = _CONFIG["incentiveTargetEvPerHome"]
"""High-adoption target (EV/home) at which the incentive crossover is evaluated —
chosen ABOVE the coldest-bin shift ceiling (~3.8) and below the mild-bin ceiling
so the optimal incentive migrates shift→curtail as the shift ceiling falls with
cold. A stress scenario, not typical adoption; the shift-ceiling CURVE is the
robust physical headline."""

# ─── Network performance state + load-growth hypothesis (2026-07-09) ─────────
# APPEND-ONLY. Real networks are UNDER-reinforced: sized for an earlier load
# that has since grown. The load-growth factor G scales the (inflexible)
# heating base; the network is SIZED at G=1 and EVALUATED under base × G. The
# performance panel across G reveals the loadedness band where flexibility is
# the right tool: below it the network is over-built (flex marginal), above it
# the base itself overloads (reinforcement required).
LOAD_GROWTH_GRID = tuple(_CONFIG["loadGrowthGrid"])
"""Load-growth factors G applied to the heating base (the network is sized at
G=1). Swept to trace utilization / overload / the flexibility window vs load."""

PERFORMANCE_REF_EV_PER_HOME = _CONFIG["performanceRefEvPerHome"]
"""Reference EV adoption (EV/home) for the flexible-vs-inflexible peak
decomposition and the feeder flexibility-window band target T."""

# ─── Probabilistic congestion-risk diagnostic (2026-07-09) ───────────────────
# APPEND-ONLY. Diagnosis before solutions: Monte-Carlo BOTH stochastic
# generators (building base + EV fleet) to estimate the probability and
# peak-severity of cold-day congestion across a realistic load-growth surface.
# No flexibility. Peaks (coincident 15-min daily max on cold days), not averages.
CONGESTION_G_GRID = tuple(_CONFIG["congestionGGrid"])
"""Base electrification growth factors G (the network is sized at G=1)."""

CONGESTION_EV_PER_HOME_GRID = tuple(_CONFIG["congestionEvPerHomeGrid"])
"""EV-adoption sweep (EV/home) for the congestion-risk surface."""

CONGESTION_K_BASE = _CONFIG["congestionKBase"]
"""Monte-Carlo realizations of the SDK building base per distinct transformer
size (expensive — SDK agent; cached in base_mc_by_size.npz)."""

CONGESTION_K_EV = _CONFIG["congestionKEv"]
"""Monte-Carlo draws of the EV fleet (cheap) crossed with the base realizations."""

CONGESTION_RISK_THRESHOLD = _CONFIG["congestionRiskThreshold"]
"""A transformer is 'at risk' when its congestion probability P(cong) exceeds
this (5% of cold-day realizations with the peak over the rating)."""

CONGESTION_AT_RISK_FRACTION = _CONFIG["congestionAtRiskFraction"]
"""Network first-risk trigger: the smallest growth scenario at which this
fraction of transformers cross CONGESTION_RISK_THRESHOLD."""

# ─── Phase-imbalance diagnostic (3-phase MV, 2026-07-09) ─────────────────────
# APPEND-ONLY. In the HQ topology the LV is single-phase 240 V split-phase; the
# phase imbalance is at 25 kV MV, where single-phase pole transformers are spread
# across the three phases. Stochastic EV adoption that clusters on one phase's
# transformers overloads/undervolts that phase. Diagnostic — no flexibility.
PHASE_EV_GRID = tuple(_CONFIG["phaseEvGrid"])
"""EV-adoption sweep (EV/home) for the phase-imbalance diagnostic."""

PHASE_MC_DRAWS = _CONFIG["phaseMcDraws"]
"""Monte-Carlo draws of which homes adopt EVs (per-transformer Poisson counts);
the phase imbalance emerges from the stochastic clustering of adopters."""

PHASE_R0_MULT = _CONFIG["phaseR0Mult"]
"""Zero-sequence line resistance multiplier (r0 = PHASE_R0_MULT * r1) — a
standard overhead-distribution assumption; calibratable, documented."""

PHASE_X0_MULT = _CONFIG["phaseX0Mult"]
"""Zero-sequence line reactance multiplier (x0 = PHASE_X0_MULT * x1)."""

PHASE_RISK_THRESHOLD = _CONFIG["phaseRiskThreshold"]
"""P(any MV phase < CSA 0.917 pu) above which the scenario is 'at risk' — used
for the first-risk adoption trigger."""

# ─── Probabilistic voltage-risk diagnostic (2026-07-13) ──────────────────────
# APPEND-ONLY. Completes the diagnostic's voltage layer: the probability and
# severity of LV undervoltage on the governed feeder under EV adoption, MC over
# the EV fleet x cold days with balanced AC power flow. Diagnostic — no
# flexibility. Peaks (min voltage at the coincident-peak hour), not averages.
VOLTAGE_EV_GRID = tuple(_CONFIG["voltageEvGrid"])
"""EV-adoption sweep (EV/home) for the voltage-risk diagnostic."""

VOLTAGE_MC_DRAWS = _CONFIG["voltageMcDraws"]
"""Monte-Carlo resamples of the EV fleet crossed with the cold days."""

VOLTAGE_RISK_THRESHOLD = _CONFIG["voltageRiskThreshold"]
"""P(min LV voltage < CSA normal-low) above which the scenario is 'at risk' —
used for the first-risk adoption trigger."""

# ── Full-net probabilistic voltage diagnostic (analyze_voltage_risk_network) ──
# The full-network sibling of the governed voltage stage: the deterministic
# validate_powerflow network min LV is 0.942/0.931/0.916/0.900 pu at
# 0/0.5/1/1.5 EV/home, so first-risk is expected FINITE. MC over cold days x
# resampled EV fleets, one full-net lightsim solve per (day, draw, level) at the
# network coincident-peak hour. Reuses VOLTAGE_EV_GRID / VOLTAGE_RISK_THRESHOLD /
# VOLTAGE_LIMITS_PU / COLD_DAY_TMEAN_C / SLACK_VM_PU / SEED.
VOLTAGE_NET_MC_DRAWS = _CONFIG["voltageNetMcDraws"]
# Fleet size whose per-EV mean is the uniform per-home EV overlay shape. Large
# enough for a stable mean; draw-to-draw variance is secondary to the cold-day
# weather axis (163 days), which dominates the undervoltage probability.
VOLTAGE_NET_EV_POOL = _CONFIG["voltageNetEvPool"]

# ── Realistic residential base: electric DHW tank + background split ──────────
# The single-R RC envelope couples peak and energy (no single R hits both HQ
# targets: peak 10-15 kW AND energy 25-30 MWh). QC all-electric homes peak higher
# for the same energy because of the electric water-heater tank (a ~4.5 kW element
# recovering after clustered morning/evening draws) — currently smoothed into the
# ARX background. `dhw_tank_annual` models it explicitly; `BG_SCALE` removes the
# double-counted DHW from the background. Provenance: spec
# 2026-07-14-ev-hosting-flex-realistic-building-base-dhw. INITIAL values; the final
# ones are fixed by calibrate_base.py (Task 4) to land the targets.
DHW_TANK_L = _CONFIG["dhwTankL"]  # 60-gal tank water volume (L)
DHW_ELEMENT_KW = _CONFIG["dhwElementKw"]  # resistive element power (kW), standard QC
DHW_T_SET = _CONFIG["dhwTSet"]  # thermostat setpoint (deg C)
DHW_T_LOW = _CONFIG["dhwTLow"]  # element turns on below this (deg C)
DHW_T_AMB = _CONFIG["dhwTAmb"]  # tank ambient (indoor) (deg C)
DHW_UA_KW_PER_K = _CONFIG[
    "dhwUaKwPerK"
]  # standby heat loss (kW/K), well-insulated tank
DHW_DAILY_L_MEAN = _CONFIG["dhwDailyLMean"]  # mean daily hot-water draw per home (L)
DHW_DAILY_L_STD = _CONFIG["dhwDailyLStd"]  # per-home draw variability (L)
DHW_DAILY_L_MIN = _CONFIG["dhwDailyLMin"]  # floor on the per-home daily draw (L)
# DEPRECATED 2026-07-16 (smooth-occupancy fix): the sparse on/off draw schedule
# caused a coincident aggregate step. dhw_tank_annual no longer reads this; the
# continuous dhw_draw_profile() replaces it. Kept for provenance / diff tests.
DHW_DRAW_WEIGHTS = {  # hour-of-day draw weights (occupancy-clustered)
    6: 0.09,
    7: 0.17,
    8: 0.11,
    12: 0.05,
    17: 0.10,
    18: 0.15,
    19: 0.14,
    20: 0.09,
    21: 0.04,
}
DHW_INLET_MIN_C = _CONFIG["dhwInletMinC"]  # cold-water inlet, winter (deg C)
DHW_INLET_MAX_C = _CONFIG["dhwInletMaxC"]  # cold-water inlet, summer (deg C)
DHW_SEED_SALT = _CONFIG[
    "dhwSeedSalt"
]  # RNG salt so DHW draws are independent of the base seed
BG_SCALE = _CONFIG["bgScale"]  # ARX background scale (remove double-counted DHW)

# ── Pilar-2: network non-wires value (analyze_nonwires_value) ─────────────────
# Deferral of reinforcement ($ NPV + transformer-years) as EV adoption ramps.
# Cost anchors are literature-illustrative (like the pilar-1 WTA): the physical
# crossing (A0/A1) is the robust result, the $ are illustrative. Spec
# 2026-07-14-ev-hosting-flex-nonwires-network-value.
TRAFO_CAPEX_PER_KVA = _CONFIG[
    "trafoCapexPerKva"
]  # $/kVA INSTALLED reinforcement (hardware+labor+
#                                   outage); reconciles with pilar-1 CAPEX_UPGRADE
#                                   8000 / 75 kVA = ~107 (raw transformer hardware
#                                   is only ~$20-40/kVA — too low; the flex has no
#                                   value against trivially-cheap reinforcement).
SUBSTATION_CAPEX_PER_MVA = _CONFIG[
    "substationCapexPerMva"
]  # $/MVA substation reinforcement (~$15-30k/MVA)
# ---------------------------------------------------------------------------
# EV adoption anchored to Québec reality (2026-07-30)
#
# The previous grid (0.5 ... 3.0 EV/home) spanned scenarios that CANNOT occur:
# 2.0 and 3.0 EV per home exceed total household vehicle ownership in Québec.
# It also had no resolution where planning actually happens -- its LOWEST point
# was already 4.5x today's adoption. Both ends are now anchored to published
# figures rather than chosen.
# ---------------------------------------------------------------------------

QC_LIGHT_VEHICLES = _CONFIG["qcLightVehicles"]
"""Automobiles + light trucks in circulation in Québec, 2021.

Source: Statistique Québec, "Véhicules en circulation".
"""

QC_RESIDENTIAL_ACCOUNTS = _CONFIG["qcResidentialAccounts"]
"""Hydro-Québec residential customer accounts, 2024.

Source: Hydro-Québec Rapport annuel 2024, Operating Statistics. Used as the
per-home denominator because it is the same "home" this study models -- an HQ
residential service -- and it is a published hard number.
"""

QC_PLUGIN_VEHICLES_2026 = _CONFIG["qcPluginVehicles2026"]
"""Plug-in vehicles registered in Québec, 2026 (6.15 % of the fleet).

Source: SAAQ statistics compiled by AVÉQ.
"""

EV_PER_HOME_TODAY = QC_PLUGIN_VEHICLES_2026 / QC_RESIDENTIAL_ACCOUNTS
"""Québec EV adoption TODAY: 0.109 EV per residential account."""

EV_PER_HOME_SATURATION = QC_LIGHT_VEHICLES / QC_RESIDENTIAL_ACCOUNTS
"""Ceiling: 1.32 EV/home = every household light vehicle electrified.

A fleet-mean adoption above this is not a scenario, it is an impossibility.
NOTE this bounds the fleet MEAN only -- under clustered adoption an individual
transformer can exceed it (see ``CLUSTER_MAX_RATE``), which is precisely why
the clustered case is the base case.
"""

RAMP_MAX_EV_PER_HOME = EV_PER_HOME_SATURATION
"""Adoption ceiling of the ramp (EV/home).

Anchored to ``EV_PER_HOME_SATURATION`` (1.32 = every household light vehicle
electrified, 5.5M vehicles / 4,178,346 residential accounts). Was 2.0, which
modelled a future with more EVs per home than Québec has VEHICLES per home —
so any crossing placed above 1.32 was unreachable by construction and silently
became 'never happens'."""
RAMP_HORIZON_YEARS = _CONFIG["rampHorizonYears"]  # planning horizon (years)
RAMP_MIDPOINT_YEAR = _CONFIG[
    "rampMidpointYear"
]  # logistic S-curve midpoint (year of MAX/2)
RAMP_STEEPNESS = _CONFIG["rampSteepness"]  # logistic growth rate
RAMP_SHAPE = _CONFIG["rampShape"]  # "logistic" | "linear"
NONWIRES_ADOPTION_GRID = tuple(round(0.1 * i, 6) for i in range(21))  # 0.0..2.0
NONWIRES_CURTAIL_TOLERANCE = _CONFIG[
    "nonwiresCurtailTolerance"
]  # max curtailed EV-energy fraction before flex
#                                    is unacceptable (the reliability side of A1)

# ── Credibility layer: confidence intervals on the headlines (analyze_credibility)
# K realizations vary the building/EV seeds AND a synthetic winter-severity
# temperature anomaly (a cold year vs mild year); the point headlines firm/flex/
# breakeven become P5/P50/P95 distributions. Single TMY -> the weather axis is a
# synthetic severity proxy (uniform per-day offset), not measured weather years.
CREDIBILITY_K = _CONFIG["credibilityK"]  # number of realizations
WEATHER_SIGMA_C = _CONFIG[
    "weatherSigmaC"
]  # winter-severity anomaly std (deg C, inter-annual)
CREDIBILITY_WEATHER_SALT = _CONFIG[
    "credibilityWeatherSalt"
]  # RNG salt for the per-realization temp offsets
CREDIBILITY_EV_SALT = _CONFIG[
    "credibilityEvSalt"
]  # EV-fleet seed multiplier per realization

# ── DHW realism: smooth occupancy draw profile + per-home tank diversity ──────
# The old sparse DHW_DRAW_WEIGHTS (zeros between clusters, identical per home)
# produced a coincident on/off step -> a near-vertical ramp in the aggregate.
# Replace it with a continuous occupancy profile (baseline all-day + smooth
# morning/evening Gaussians) and jitter the tank parameters per home so reheats
# stagger. Spec 2026-07-16-ev-hosting-flex-dhw-smooth-occupancy. INITIAL values;
# calibrate_base.py fixes the finals (Task 3).
DHW_BASE_WEIGHT = _CONFIG[
    "dhwBaseWeight"
]  # all-day baseline draw weight (no zero hours)
DHW_MORNING_HOUR = _CONFIG["dhwMorningHour"]  # morning occupancy peak (local hour)
DHW_MORNING_SIGMA = _CONFIG["dhwMorningSigma"]  # morning peak width (h)
DHW_MORNING_AMP = _CONFIG["dhwMorningAmp"]  # morning peak amplitude
DHW_EVENING_HOUR = _CONFIG["dhwEveningHour"]  # evening occupancy peak (local hour)
DHW_EVENING_SIGMA = _CONFIG["dhwEveningSigma"]  # evening peak width (h)
DHW_EVENING_AMP = _CONFIG["dhwEveningAmp"]  # evening peak amplitude
DHW_SETPOINT_JITTER_C = _CONFIG["dhwSetpointJitterC"]  # per-home setpoint std (deg C)
DHW_DEADBAND_JITTER_C = _CONFIG["dhwDeadbandJitterC"]  # per-home deadband std (deg C)
DHW_ELEMENT_JITTER_KW = _CONFIG["dhwElementJitterKw"]  # per-home element-power std (kW)
DHW_TANK_L_JITTER_L = _CONFIG["dhwTankLJitterL"]  # per-home tank-volume std (L)

# ── Cold-tail insurance study (analyze_cold_insurance) ───────────────────────
# Hosting capacity is a DISTRIBUTION under winter-severity uncertainty (the
# credibility layer found firm = {2:1, 3:10, 4:20, 5:18, 6:1} over K=50, i.e.
# planning at the point estimate leaves the feeder short ~22 % of years). This
# study prices flexibility as INSURANCE against that cold tail and compares it to
# reinforcement AT AN EQUAL RELIABILITY TARGET. Spec
# 2026-07-28-ev-hosting-flex-cold-tail-insurance. Reuses the credibility seeds
# (CREDIBILITY_K / WEATHER_SIGMA_C / CREDIBILITY_WEATHER_SALT /
# CREDIBILITY_EV_SALT) so the two studies share one firm distribution.
INSURANCE_ADOPTION_GRID = tuple(range(1, 13))  # target EV counts on the 6-home feeder
INSURANCE_RELIABILITY_TARGET = _CONFIG[
    "insuranceReliabilityTarget"
]  # both strategies must cover >= 95 % of years
INSURANCE_REF_ADOPTION = _CONFIG[
    "insuranceRefAdoption"
]  # 1 EV/home on the governed feeder (pin reference)

# ---------------------------------------------------------------------------
# Fleet triage (2026-07-29)
#
# The per-asset flexibility results (firm -> flexible on the governed feeder)
# were never scaled to the 540-transformer fleet, so the study could not say
# how MANY assets flexibility actually defers. The triage classifies every
# pole transformer into: never binds / flexibility defers it / needs steel.
#
# It also corrects a measurement artefact. `apply_curtailment_contracts` gates
# the flexible count on `residual_hours <= base_floor`, but under FULL
# enrollment the backstop can always hold the feeder (it simply curtails more),
# so that gate is near-vacuous and the reported flexible count equalled
# POOL_MAX_ANNUAL (12) -- a pool-size artefact, not a physical limit. Measured
# on the governed feeder, 12 EVs curtail only 2.0 % of EV energy, a fifth of
# the tolerance. Gating on TRIAGE_CURTAIL_TOLERANCE instead gives 20 EVs
# (6.5 % curtailed), i.e. firm 5 -> flexible 20 (+300 %, not +140 %).
# ---------------------------------------------------------------------------

TRIAGE_ADOPTION_GRID = tuple(_CONFIG["triageAdoptionGrid"])
"""EV-per-home adoption levels at which the fleet is triaged."""

TRIAGE_CURTAIL_TOLERANCE = NONWIRES_CURTAIL_TOLERANCE
"""Max curtailed EV-energy fraction a flexibility contract may impose.

This -- not feasibility -- is what bounds the flexible count. The constraint is
the SERVICE the customer is denied, so the limit is a commercial term, not a
physical one.
"""

TRIAGE_POOL_PER_HOME = _CONFIG["triagePoolPerHome"]
"""EV-per-home pool depth searched for the flexible count.

Must exceed the largest adoption on the grid by enough headroom that the
tolerance binds before the pool does -- the artefact this stage corrects.
"""

TRIAGE_K_BASE = _CONFIG["triageKBase"]
"""Base realizations per size class (the triage reports the median)."""

TRIAGE_BASE_FLOOR_TOLERANCE_H = _CONFIG["triageBaseFloorToleranceH"]
"""Base-alone overload hours a transformer may carry before it needs steel.

An EV flexibility contract can only curtail EV load. In the hours where the
BUILDING BASE alone already exceeds the rating there is nothing for the
contract to shed, so no amount of enrollment defers that asset -- it is
constrained by winter heating, not by cars. Assets over this tolerance are
reported as `base_constrained` and never counted as deferred.

Default 0.0 (any base-alone overload disqualifies) is the conservative reading.
The emitted `base_floor_hours` per size class lets a reader apply a laxer
threshold -- utilities do tolerate brief overloads under dynamic rating -- so
the classification stays auditable rather than resting on one chosen number.
"""

TRIAGE_DISPERSION_GRID = CLUSTER_DISPERSION_GRID
"""Adoption-dispersion levels swept by the fleet triage.

Reuses the clustered-adoption stage's grid so the two studies are directly
comparable. `0.0` is the uniform reference, NOT the base case.
"""

TRIAGE_BASE_DISPERSION = _CONFIG["triageBaseDispersion"]
"""Headline dispersion for the fleet triage (Gini ~0.37 across transformers).

EV ownership is spatially correlated -- income, detached housing with a
driveway, neighbour effects -- so a uniform allocation understates the stress
on the worst last-mile transformer while preserving the fleet total. The
clustered-adoption stage measured the consequence: at 1 EV/home the worst
transformer goes from 132 % loading (uniform) to 237 % at this dispersion.

0.7 is the MIDDLE of the swept grid, chosen so the headline is neither the
uniform fiction nor the most extreme case; the full grid is emitted so a reader
can read the sensitivity rather than trust this one choice.
"""

TRIAGE_CLUSTER_DRAWS = CLUSTER_MC_DRAWS
"""Allocation draws averaged per (adoption, dispersion) cell."""


TRIAGE_RATING_CONVENTIONS = tuple(_CONFIG["triageRatingConventions"])
"""Rating conventions the fleet triage evaluates side by side.

`static` judges every hour against the nameplate, which is defined at a 30 °C
ambient basis. `hourly_kt` scales it by the IEEE C57.91 loading capability at
each step's actual ambient. In a heating-dominated system these are not a small
correction apart: load and thermal capability are driven by the SAME variable
and rise together, so the choice changes not only HOW MUCH congestion is found
but WHAT IT IS ATTRIBUTED TO. Both are emitted so the reader sees the spread
instead of inheriting one convention silently.
"""

TRIAGE_HOTSPOT_LIMIT_C = _CONFIG["triageHotspotLimitC"]
"""Hot-spot limit defining the C57.91 capability (normal insulation life)."""

# ---------------------------------------------------------------------------
# Feeder rating convention (2026-07-30) — the study's highest-leverage choice
#
# Measured on this feeder: judging every hour against the nameplate finds 255
# of 540 transformers in trouble TODAY; the temperature-dependent rating finds
# zero. The convention moves more assets (255) than electrifying every
# household vehicle in Québec does (222). It is therefore declared here, once,
# rather than implied by each stage building its own scalar.
# ---------------------------------------------------------------------------

RATING_CONVENTION = _CONFIG["ratingConvention"]
"""How the feeder's usable rating is evaluated: 'hourly_kt' or 'static'.

'static' uses the nameplate, a rating defined at a 30 °C ambient basis.
'hourly_kt' scales it by the IEEE C57.91 loading capability at each step's
actual ambient.

In a heating-dominated feeder the load peak and the thermal capability are
driven by the SAME variable and rise together, so the nameplate systematically
understates capability in exactly the hours the load peaks. 'hourly_kt' is the
default because it is the physically correct comparison and it matches
Hydro-Québec practice; 'static' is retained so the conservative planning
convention stays reproducible for comparison.

Verified consequence: at the design cold the capability is ~1.43x nameplate,
and across the whole reachable adoption range the resulting hot spot stays
below the 110 °C normal-insulation-life limit, so the extra capability is not
borrowed against transformer life.
"""

EV_KWH_PER_YEAR = _CONFIG["evKwhPerYear"]
"""Annual energy of one EV as this study's own generator produces it (kWh).

MEASURED, not assumed: mean over a 60-EV draw from `ev_fleet_annual` on the
committed TMY (p5 2349, p95 2663). Anchored to the generator rather than to a
literature value because it multiplies a curtailed FRACTION that the same
generator produced — mixing the two would price denied energy the model never
generated. For external validity it sits just below the ~2 700–3 000 kWh/yr
reported for Canadian EVs, consistent with a cold-climate fleet that plugs in
on 60–85 % of days rather than daily.
"""
