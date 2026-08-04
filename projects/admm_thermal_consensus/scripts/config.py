"""Centralized configuration for the admm_thermal_consensus study.

All knobs are explicit and deterministic so the study reproduces exactly.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[3]
PROJECT_ROOT = ROOT / "projects" / "admm_thermal_consensus"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"
DATA_DIR = OUTPUTS_DIR / "data"
JSON_DIR = OUTPUTS_DIR / "json"
CACHE_DIR = OUTPUTS_DIR / "cache"
FIGURES_DIR = OUTPUTS_DIR / "figures"

# ── Study dimensions ────────────────────────────────────────────────
SEED = 42
N_AGENTS = 74  # literal all-electric homes behind one 400 kVA LV transformer
RESOLUTION_MINUTES = 15
DURATION_HOURS = 24
N_STEPS = DURATION_HOURS * 60 // RESOLUTION_MINUTES  # 96
STEP_HOURS = RESOLUTION_MINUTES / 60.0
WEATHER_SOURCE = "synthetic"
GENERATOR = "thermodynamic"  # exposes per-home heating vs background split

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
R_STUDY_B = 7.5           # deg C/kW  envelope resistance
P_HEAT_QUEBEC = 13.0      # kW        per-home baseboard capacity
BG_SCALE = 0.6            # -         non-HVAC background scale
HEATING_CONTROL = "hysteresis"
DHW_SEED_SALT = 91931     # separate stream for the tank fleet

# ── ADMM ────────────────────────────────────────────────────────────
ADMM_RHO = 5.0          # penalty parameter (tuned for the comfort-coupled prox)
ADMM_RELAX = 1.7        # over-relaxation factor (Boyd 3.4.3) to speed consensus
ADMM_LAMBDA = 0.15      # comfort weight (stay near thermostat baseline)
ADMM_MU = 1.0           # aggregate flattening weight
ADMM_MAX_ITERS = 500    # generous cap; tuned rho+relax converges in <~100 sweeps
ADMM_TOL = 1e-4         # on combined primal+dual residual
DEFERRABILITY_ALPHA = 0.5  # heating may modulate +/-50% around baseline per step
COMFORT_GAMMA = 2.0   # weight on the modelled indoor-temperature excursion (~+/-1 C)
COMFORT_BAND_C = 1.0  # target/reported comfort band on indoor temperature (deg C)

# ── Communication-failure sweep ────────────────────────────────────
RHO_SWEEP = (
    0.0, 0.2, 0.35, 0.42, 0.45, 0.48, 0.5, 0.52, 0.55, 0.6, 0.8, 1.0
)  # fraction of non-responsive agents; dense near the feasibility knee (~0.5)
# The knee moved when the base was recalibrated to the Québec all-electric
# archetype: the previous grid was dense over 0.8-0.9 because the uncalibrated
# load left slack up to there. With realistic load the transition from
# always-feasible to always-violating sits between 0.4 and 0.6, and the old grid
# had no point inside it -- every sampled rho above 0.6 returned probability 1.0
# for every imputation method, including no imputation at all, which made the
# comparison vacuous rather than negative.
ILLUSTRATIVE_RHO = 0.55  # non-responsive fraction shown as the degraded-comms curve

# ── Network: synthetic LV residential feeder with a real distribution trafo ──
# 74 literal dwelling units hang off one MV/LV network transformer (a dense
# multi-unit residential service), Quebec/North-American style. The uncoordinated
# winter peak overloads the transformer (~120%). No artificial scale factor: the
# aggregate (kW) is injected directly at the LV buses and the transformer thermal
# loading is the binding constraint (the classic residential winter-peak / CLPU
# limit). Hydro-Quebec primary is 25 kV (14.4/24.94 kV); the secondary is the
# North-American 120/208 V three-phase wye network voltage, not European 400 V.
POWER_FACTOR = 0.95
MV_KV = 25.0                # Hydro-Quebec medium-voltage primary (14.4/24.94 kV)
LV_KV = 0.208               # North-American 120/208 V three-phase wye secondary
# Sized 500 kVA, not 400: with the Québec all-electric calibration the 74-home
# winter peak is ~572 kW, which would sit at 150% of a 400 kVA unit -- not a
# design any utility installs, so the scenario would have been arguing from an
# asset that does not exist. 500 kVA is the next standard North-American rating
# and restores the intended premise: the uncoordinated peak overloads the
# transformer (~120%) and coordination has to bring it back under the limit.
TRANSFORMER_KVA = 500.0     # MV/LV network distribution transformer rating
N_LV_FEEDERS = 4            # parallel LV feeders leaving the transformer busbar
BUSES_PER_FEEDER = 2        # load buses along each feeder (unit clusters)
N_LV_SECTIONS = N_LV_FEEDERS * BUSES_PER_FEEDER  # total LV load buses
LV_SECTION_KM = 0.014       # length of each LV secondary section (short in-building runs)
LV_R_OHM_KM = 0.206         # LV feeder resistance
LV_X_OHM_KM = 0.080         # LV feeder reactance
LV_MAX_I_KA = 0.6           # LV feeder / bus-duct ampacity (208 V building service)
VOLTAGE_LOWER_PU = 0.95
# Short-duration winter overload limit (IEEE C57.91): nameplate (100%) is not a
# hard cliff -- cold ambient and thermal mass let a distribution transformer
# carry a brief overload without exceeding its hottest-spot limit. We adopt a
# conservative 105% planning limit for the recurring winter peak.
TRANSFORMER_LOADING_LIMIT_PCT = 105.0
LINE_LOADING_LIMIT_PCT = 105.0  # retained alias for the thermal limit

# ── Forecast-uncertainty Monte Carlo ───────────────────────────────
# For each non-responsive fraction we draw UQ_N_DRAWS random failing
# subsets and perturb their imputed heating by Gaussian forecast residuals
# (std = the imputer's CV RMSE). Worst-of-day voltage/line-loading is a
# monotone function of the daily aggregate peak, so it is read from a
# precomputed peak-MW -> (vmin, loading) curve instead of re-solving the
# full day per draw.
UQ_N_DRAWS = 200
UQ_PEAK_GRID_N = 41
UQ_PEAK_RANGE_MW = (3.4, 5.4)
UQ_BAND_LOW_PCT = 5.0
UQ_BAND_HIGH_PCT = 95.0

# ── Imputation-method comparison ───────────────────────────────────
# Representative fraction for the per-method P(violation) comparison. Placed on
# the recalibrated knee (~0.5): at 0.8 every method -- including "none" -- hit
# probability 1.0, so the comparison distinguished nothing.
COMPARISON_REP_RHO = 0.5
COMPARISON_MC_DRAWS = 100    # random silent subsets at the representative fraction

# ── TOU price (CAD/kWh) by hour, deterministic ─────────────────────
def tou_price_per_hour() -> list[float]:
    """Return a 24-length CAD/kWh time-of-use price vector."""
    price = [0.078] * 24          # off-peak
    for h in range(7, 11):
        price[h] = 0.128          # morning peak
    for h in range(16, 21):
        price[h] = 0.158          # evening peak
    return price
