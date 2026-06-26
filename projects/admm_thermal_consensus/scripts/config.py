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

# ── ADMM ────────────────────────────────────────────────────────────
ADMM_RHO = 1.0          # penalty parameter
ADMM_LAMBDA = 0.15      # comfort weight (stay near thermostat baseline)
ADMM_MU = 1.0           # aggregate flattening weight
ADMM_MAX_ITERS = 300
ADMM_TOL = 1e-4         # on combined primal+dual residual
DEFERRABILITY_ALPHA = 0.5  # heating may modulate +/-50% around baseline per step

# ── Communication-failure sweep ────────────────────────────────────
RHO_SWEEP = (
    0.0, 0.2, 0.4, 0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.9, 1.0
)  # fraction of non-responsive agents; dense near the flexibility-exhaustion knee
ILLUSTRATIVE_RHO = 0.8  # non-responsive fraction shown as the degraded-comms curve

# ── Network: synthetic LV residential feeder with a real distribution trafo ──
# 80 literal homes hang off one MV/LV transformer; the uncoordinated winter peak
# overloads it (~112%). No artificial scale factor: the home aggregate (kW) is
# injected directly at LV buses and the transformer thermal loading is the
# binding constraint (the classic residential winter-peak / CLPU limit).
POWER_FACTOR = 0.95
MV_KV = 25.0                # Quebec-style medium-voltage primary
LV_KV = 0.4                 # balanced low-voltage secondary equivalent
TRANSFORMER_KVA = 400.0     # MV/LV distribution transformer rating
N_LV_FEEDERS = 4            # parallel LV feeders leaving the transformer busbar
BUSES_PER_FEEDER = 2        # load buses along each feeder (home clusters)
N_LV_SECTIONS = N_LV_FEEDERS * BUSES_PER_FEEDER  # total LV load buses
LV_SECTION_KM = 0.05        # length of each LV cable section
LV_R_OHM_KM = 0.206         # NAYY-style LV cable resistance
LV_X_OHM_KM = 0.080         # LV cable reactance
LV_MAX_I_KA = 0.275         # LV cable ampacity
VOLTAGE_LOWER_PU = 0.95
TRANSFORMER_LOADING_LIMIT_PCT = 100.0
LINE_LOADING_LIMIT_PCT = 100.0  # retained alias for the thermal limit

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
COMPARISON_REP_RHO = 0.6     # representative fraction for per-method P(violation)
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
