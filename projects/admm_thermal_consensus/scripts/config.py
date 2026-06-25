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
RHO_SWEEP = (0.0, 0.2, 0.4, 0.6, 0.8)  # fraction of non-responsive agents

# ── Network (IEEE-33) ──────────────────────────────────────────────
POWER_FACTOR = 0.95
TARGET_FEEDER_PEAK_MW = 4.6  # uncoordinated peak is scaled to this on the feeder
VOLTAGE_LOWER_PU = 0.95
LINE_LOADING_LIMIT_PCT = 100.0
TARGET_UNCOORD_LINE_LOADING_PCT = 115.0  # calibrate trunk ampacity to this at the uncoordinated peak

# ── TOU price (CAD/kWh) by hour, deterministic ─────────────────────
def tou_price_per_hour() -> list[float]:
    """Return a 24-length CAD/kWh time-of-use price vector."""
    price = [0.078] * 24          # off-peak
    for h in range(7, 11):
        price[h] = 0.128          # morning peak
    for h in range(16, 21):
        price[h] = 0.158          # evening peak
    return price
