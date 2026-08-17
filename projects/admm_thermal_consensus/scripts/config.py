"""Centralized configuration for the admm_thermal_consensus study.

All knobs are explicit and deterministic so the study reproduces exactly.

Since Phase 19 the study values are declared in ``project.yaml`` under
``spec.inputs.studyConfig`` (config-as-contract): this module reads them so
``project.yaml`` is the single source of truth and the old ``config.py``-as-
code duplication is gone. The values are identical to the pre-migration
configuration (identity-preserving). Paths remain derived here — they are
layout, not study parameters.
"""

from __future__ import annotations

from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
DATA_DIR = OUTPUTS_DIR / "data"
JSON_DIR = OUTPUTS_DIR / "json"
CACHE_DIR = OUTPUTS_DIR / "cache"
FIGURES_DIR = OUTPUTS_DIR / "figures"


def _study_config() -> dict:
    """Load the declared ``spec.inputs.studyConfig`` block from project.yaml.

    Raises:
        ValueError: A located error naming the project file and the input key
            when ``studyConfig`` is absent or not a mapping (never a bare
            ``KeyError``), so a dropped block is diagnosable from the message.
    """
    project_file = PROJECT_ROOT / "project.yaml"
    raw = yaml.safe_load(project_file.read_text(encoding="utf-8"))
    inputs = (raw or {}).get("spec", {}).get("inputs", {})
    if not isinstance(inputs, dict) or "studyConfig" not in inputs:
        available = ", ".join(sorted(str(k) for k in inputs)) or "none declared"
        raise ValueError(
            f"{project_file}: spec.inputs.studyConfig not found "
            f"(available inputs: {available}). Remediation: declare the study "
            "knobs under spec.inputs.studyConfig in project.yaml."
        )
    config = inputs["studyConfig"]
    if not isinstance(config, dict):
        raise ValueError(
            f"{project_file}: spec.inputs.studyConfig must be a mapping, "
            f"found {type(config).__name__}"
        )
    return config


_CONFIG = _study_config()

# ── Study dimensions ────────────────────────────────────────────────
SEED = _CONFIG["seed"]
N_AGENTS = _CONFIG[
    "nAgents"
]  # literal all-electric homes behind one 400 kVA LV transformer
RESOLUTION_MINUTES = _CONFIG["resolutionMinutes"]
DURATION_HOURS = _CONFIG["durationHours"]
N_STEPS = DURATION_HOURS * 60 // RESOLUTION_MINUTES  # 96
STEP_HOURS = RESOLUTION_MINUTES / 60.0
WEATHER_SOURCE = _CONFIG["weatherSource"]
GENERATOR = _CONFIG["generator"]  # exposes per-home heating vs background split

# ─── Québec all-electric calibration ───────────────────────────────────
# Propagated from projects/ev_hosting_flex (CALIBRATION.md). This study models
# cold-climate all-electric dwellings, and the SDK-native defaults are not that
# archetype: R=11 yields a ~6.6 kW/home peak against the 10-15 kW Hydro-Québec
# band, and the study's own 74-home aggregate came out 38% below measured
# all-electric homes on temperature-matched cold days.
#
# Same operating point as ev_hosting_flex so the two studies stand on one
# building model: envelope R, baseboard capacity, background scale, the DHW
# tank (a ~4.5 kW element the ARX background had smoothed away), and per-zone
# latching thermostats.
R_STUDY_B = _CONFIG["rStudyB"]  # deg C/kW  envelope resistance
P_HEAT_QUEBEC = _CONFIG["pHeatQuebec"]  # kW per-home baseboard capacity
BG_SCALE = _CONFIG["bgScale"]  # non-HVAC background scale
HEATING_CONTROL = _CONFIG["heatingControl"]
DHW_SEED_SALT = _CONFIG["dhwSeedSalt"]  # separate stream for the tank fleet

# ── ADMM ────────────────────────────────────────────────────────────
ADMM_RHO = _CONFIG["admmRho"]  # penalty parameter (tuned for the comfort-coupled prox)
ADMM_RELAX = _CONFIG["admmRelax"]  # over-relaxation factor (Boyd 3.4.3)
ADMM_LAMBDA = _CONFIG["admmLambda"]  # comfort weight (stay near thermostat baseline)
ADMM_MU = _CONFIG["admmMu"]  # aggregate flattening weight
ADMM_MAX_ITERS = _CONFIG[
    "admmMaxIters"
]  # generous cap; tuned rho+relax converges < ~100
ADMM_TOL = _CONFIG["admmTol"]  # on combined primal+dual residual
DEFERRABILITY_ALPHA = _CONFIG[
    "deferrabilityAlpha"
]  # heating may modulate +/-50% per step
COMFORT_GAMMA = _CONFIG["comfortGamma"]  # weight on indoor-temperature excursion
COMFORT_BAND_C = _CONFIG[
    "comfortBandC"
]  # reported comfort band on indoor temperature (deg C)

# ── Communication-failure sweep ────────────────────────────────────
RHO_SWEEP = tuple(_CONFIG["rhoSweep"])  # fraction of non-responsive agents
# The knee moved when the base was recalibrated to the Québec all-electric
# archetype: the previous grid was dense over 0.8-0.9 because the uncalibrated
# load left slack up to there. With realistic load the transition from
# always-feasible to always-violating sits between 0.4 and 0.6, and the old grid
# had no point inside it -- every sampled rho above 0.6 returned probability 1.0
# for every imputation method, including no imputation at all, which made the
# comparison vacuous rather than negative.
ILLUSTRATIVE_RHO = _CONFIG["illustrativeRho"]  # shown as the degraded-comms curve

# ── Network: synthetic LV residential feeder with a real distribution trafo ──
# 74 literal dwelling units hang off one MV/LV network transformer (a dense
# multi-unit residential service), Quebec/North-American style. The uncoordinated
# winter peak overloads the transformer (~120%). No artificial scale factor: the
# aggregate (kW) is injected directly at the LV buses and the transformer thermal
# loading is the binding constraint (the classic residential winter-peak / CLPU
# limit). Hydro-Quebec primary is 25 kV (14.4/24.94 kV); the secondary is the
# North-American 120/208 V three-phase wye network voltage, not European 400 V.
POWER_FACTOR = _CONFIG["powerFactor"]
MV_KV = _CONFIG["mvKv"]  # Hydro-Quebec medium-voltage primary (14.4/24.94 kV)
LV_KV = _CONFIG["lvKv"]  # North-American 120/208 V three-phase wye secondary
# Sized 500 kVA, not 400: with the Québec all-electric calibration the 74-home
# winter peak is ~572 kW, which would sit at 150% of a 400 kVA unit -- not a
# design any utility installs, so the scenario would have been arguing from an
# asset that does not exist. 500 kVA is the next standard North-American rating
# and restores the intended premise: the uncoordinated peak overloads the
# transformer (~120%) and coordination has to bring it back under the limit.
TRANSFORMER_KVA = _CONFIG[
    "transformerKva"
]  # MV/LV network distribution transformer rating
N_LV_FEEDERS = _CONFIG[
    "nLvFeeders"
]  # parallel LV feeders leaving the transformer busbar
BUSES_PER_FEEDER = _CONFIG["busesPerFeeder"]  # load buses along each feeder
N_LV_SECTIONS = N_LV_FEEDERS * BUSES_PER_FEEDER  # total LV load buses
LV_SECTION_KM = _CONFIG["lvSectionKm"]  # length of each LV secondary section
LV_R_OHM_KM = _CONFIG["lvROhmKm"]  # LV feeder resistance
LV_X_OHM_KM = _CONFIG["lvXOhmKm"]  # LV feeder reactance
LV_MAX_I_KA = _CONFIG[
    "lvMaxIKa"
]  # LV feeder / bus-duct ampacity (208 V building service)
VOLTAGE_LOWER_PU = _CONFIG["voltageLowerPu"]
# Short-duration winter overload limit (IEEE C57.91): nameplate (100%) is not a
# hard cliff -- cold ambient and thermal mass let a distribution transformer
# carry a brief overload without exceeding its hottest-spot limit. We adopt a
# conservative 105% planning limit for the recurring winter peak.
TRANSFORMER_LOADING_LIMIT_PCT = _CONFIG["transformerLoadingLimitPct"]
LINE_LOADING_LIMIT_PCT = _CONFIG[
    "lineLoadingLimitPct"
]  # retained alias for the thermal limit

# ── Forecast-uncertainty Monte Carlo ───────────────────────────────
# For each non-responsive fraction we draw UQ_N_DRAWS random failing
# subsets and perturb their imputed heating by Gaussian forecast residuals
# (std = the imputer's CV RMSE). Worst-of-day voltage/line-loading is a
# monotone function of the daily aggregate peak, so it is read from a
# precomputed peak-MW -> (vmin, loading) curve instead of re-solving the
# full day per draw.
UQ_N_DRAWS = _CONFIG["uqNDraws"]
UQ_PEAK_GRID_N = _CONFIG["uqPeakGridN"]
UQ_PEAK_RANGE_MW = tuple(_CONFIG["uqPeakRangeMw"])
UQ_BAND_LOW_PCT = _CONFIG["uqBandLowPct"]
UQ_BAND_HIGH_PCT = _CONFIG["uqBandHighPct"]

# ── Imputation-method comparison ───────────────────────────────────
# Representative fraction for the per-method P(violation) comparison. Placed on
# the recalibrated knee (~0.5): at 0.8 every method -- including "none" -- hit
# probability 1.0, so the comparison distinguished nothing.
COMPARISON_REP_RHO = _CONFIG["comparisonRepRho"]
COMPARISON_MC_DRAWS = _CONFIG[
    "comparisonMcDraws"
]  # random silent subsets at the representative fraction


# ── TOU price (CAD/kWh) by hour, deterministic ─────────────────────
def tou_price_per_hour() -> list[float]:
    """Return a 24-length CAD/kWh time-of-use price vector."""
    price = [0.078] * 24  # off-peak
    for h in range(7, 11):
        price[h] = 0.128  # morning peak
    for h in range(16, 21):
        price[h] = 0.158  # evening peak
    return price
