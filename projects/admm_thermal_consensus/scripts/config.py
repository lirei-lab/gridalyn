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
N_AGENTS = 30
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

# ── Network (IEEE-33) ──────────────────────────────────────────────
POWER_FACTOR = 0.95
TARGET_FEEDER_PEAK_MW = 4.6  # uncoordinated peak is scaled to this on the feeder
VOLTAGE_LOWER_PU = 0.95
LINE_LOADING_LIMIT_PCT = 100.0
TARGET_UNCOORD_LINE_LOADING_PCT = 115.0  # calibrate trunk ampacity to this at the uncoordinated peak

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

# ── TOU price (CAD/kWh) by hour, deterministic ─────────────────────
def tou_price_per_hour() -> list[float]:
    """Return a 24-length CAD/kWh time-of-use price vector."""
    price = [0.078] * 24          # off-peak
    for h in range(7, 11):
        price[h] = 0.128          # morning peak
    for h in range(16, 21):
        price[h] = 0.158          # evening peak
    return price
