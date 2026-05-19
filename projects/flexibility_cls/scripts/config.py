"""
config.py – Centralized Paper Analysis Configuration
Unifies structural analysis variables and limits globally across the paper tracking scripts
to guarantee mathematical consistency when rendering bounds and thresholds.
"""

from pathlib import Path
import json

ROOT = Path(__file__).parents[3]
PROJECT_ROOT = ROOT / "projects" / "flexibility_cls"
PROJECT_OUTPUTS_DIR = PROJECT_ROOT / "outputs"
PROJECT_CACHE_DIR = PROJECT_OUTPUTS_DIR / "cache"
TOPOLOGY_CACHE_MANIFEST = PROJECT_CACHE_DIR / "topology_cache_manifest.json"

# ─── Load underlying physical system configuration ───────────────
with open(ROOT / "configs/grid/config.json") as f:
    GRID_CONFIG = json.load(f)

N_BUILDINGS = GRID_CONFIG["loads"]["n_buildings_cache"]  # Base layout structure

# ─── Load isolated analytical evaluation limits ───────────────
PAPER_CONFIG = {
    "ev_analysis": {
        # IEEE C57.91-2011 ONAN distribution transformer – 15 MVA
        # Sized for the Trois-Rivières primary substation serving 3 235 buildings.
        # theta_max = 110 °C → normal life expectancy limit (IEEE C57.91 §7).
        # At 30 °C ambient (design point) K=1 gives θ_H ≈ 30+55+25 = 110 °C.
        # Dynamic thermal limit at -22 °C winter: ~20.1 MW (K ≈ 1.41 × P_rated),
        # creating realistic congestion as high-EV peak realizations approach or exceed it.
        "transformer_mva": 15.0,
        "power_factor": 0.95,
        "theta_max_c": 110.0,
        "p_limit_kw": None        # Let the physical thermal model govern the limit
    },
    "simulation": {
        "n_realizations": 30,
        "res_minutes": 5,
        "seed_base": 0,
        "seed": 42
    },
    "network": {
        "n_feeder_blocks": 160,
        "participation_rate": 0.30,
    },
    "market": {
        "hard_cls_price": 10.0,
        "non_delivery_penalty": 10.0,
        "delivery_failure_rate": 0.05,
        "clearing_interval_h": 0.5,
    },
    "ev": {
        # 240 V / 16 A residential Level-2 charger used by the EV simulator.
        "charger_kw": 3.84,
    },
    "scenarios": {
        "penetrations": [0, 10, 20, 30, 40],
        "default_target": 40
    }
}

# The analytical capacity target (20 MVA) supersedes the native PP default explicitly for EV scaling limits
S_RATED_MVA = PAPER_CONFIG["ev_analysis"]["transformer_mva"]
S_RATED_KVA = S_RATED_MVA * 1000.0
THETA_MAX   = PAPER_CONFIG["ev_analysis"]["theta_max_c"]
PF          = PAPER_CONFIG["ev_analysis"]["power_factor"]
P_RATED_KW  = S_RATED_KVA * PF

if PAPER_CONFIG["ev_analysis"].get("p_limit_kw") is not None:
    P_LIMIT_KW = PAPER_CONFIG["ev_analysis"]["p_limit_kw"]
else:
    # Legacy alias used by the market/network classes for the static nameplate
    # active-power rating. Dynamic operating limits are computed with
    # TransformerThermalModel.max_load_for_temp(...), not this constant.
    P_LIMIT_KW = P_RATED_KW

N_REALIZATIONS = PAPER_CONFIG["simulation"]["n_realizations"]
RES_MINUTES    = PAPER_CONFIG["simulation"]["res_minutes"]
EV_PCT_TARGET  = PAPER_CONFIG["scenarios"]["default_target"]
EV_PERCENTAGES = PAPER_CONFIG["scenarios"]["penetrations"]
SEED_BASE      = PAPER_CONFIG["simulation"]["seed_base"]
SEED           = PAPER_CONFIG["simulation"]["seed"]
N_FEEDER_BLOCKS = PAPER_CONFIG["network"]["n_feeder_blocks"]
PARTICIPATION_RATE = PAPER_CONFIG["network"]["participation_rate"]
HARD_CLS_PRICE = PAPER_CONFIG["market"]["hard_cls_price"]
NON_DELIVERY_PENALTY = PAPER_CONFIG["market"]["non_delivery_penalty"]
DELIVERY_FAILURE_RATE = PAPER_CONFIG["market"]["delivery_failure_rate"]
MARKET_CLEARING_INTERVAL_H = PAPER_CONFIG["market"]["clearing_interval_h"]
EV_CHARGER_KW = PAPER_CONFIG["ev"]["charger_kw"]
