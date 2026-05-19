"""
network.py – HV/MV Distribution Substation (configured via configs/grid/config.json).

Topology
--------
  HV bus (←config) ──[S_rated MVA transformer]──[MV bus (←config)]
                                                               │
                          ┌────────────┬──────────────┬────────┴──────────┬──────────────┐
                       Feeder 1    Feeder 2        Feeder 3           Feeder 4

Each 25 kV feeder serves residential customers via distribution LV transformers
(typically 50–167 kVA, pole-mounted or pad-mounted).

The EV capacity limitation study aggregates 3,235 stochastic dwellings into 160 market feeder
blocks for Soft-CLS clearing, with 30% of blocks enrolled in the market.

Physical power parameters per block-level building object:
  P_heat_max  : ~80 kW (50 units × 1.6 kW baseboards, ON/OFF controlled)
  P_bg_mean   : ~25 kW  (50 units × 0.5 kW background)
  EV charger  : 3.84 kW per EV × ~40 EVs at peak = ~150 kW per block
"""

from __future__ import annotations

import json
from pathlib import Path
from dataclasses import dataclass, field
import numpy as np
from gridalyn.assets.datagen.grid.transformer_thermal import TransformerThermalModel

# ─────────────────────────────────────────────────────────────────────────────
# Substation specification (Dynamically synced)
# ─────────────────────────────────────────────────────────────────────────────
_root = Path(__file__).parents[4]
with open(_root / "configs/grid/config.json", "r") as f:
    _config = json.load(f)

TRANSFORMER_MVA = _config["transformers"]["mv_hv"]["capacity_kva"] / 1000.0
TRANSFORMER_KVA = TRANSFORMER_MVA * 1000 
VOLTAGE_HV_KV   = 120.0          # primary (HQ transmission standard)
VOLTAGE_MV_KV   = 25.0           # secondary / distribution feeder voltage
PF_NOMINAL      = 0.95           # nominal power factor

P_RATED_KW      = TRANSFORMER_KVA * PF_NOMINAL       
P_EMERGENCY_KW  = P_RATED_KW * 1.20                  
P_LIMIT_KW      = TRANSFORMER_KVA * 1.0       # Legacy Static DOE
THETA_MAX       = _config["transformers"]["mv_hv"].get("theta_max_c", 110.0)

# MV feeder current at 25 kV (3-phase): I = S / (√3 · V)
I_MAX_A         = (TRANSFORMER_KVA * 1000) / (1.732 * VOLTAGE_MV_KV * 1000)

# Simulation scale: each "building" object = N_UNITS_PER_BLOCK households
N_UNITS_PER_BLOCK = 50
N_BLOCKS_TOTAL    = 160


@dataclass
class Feeder:
    name: str
    n_blocks: int          
    impedance_pu: float = 0.02   


@dataclass
class MVNetwork:
    """
    Simplified radial MV network. Uses dynamic Unified Thermal Model + aggregate power balance.
    """
    feeders: list[Feeder] = field(default_factory=lambda: [
        Feeder("Feeder-1", n_blocks=40),
        Feeder("Feeder-2", n_blocks=40),
        Feeder("Feeder-3", n_blocks=40),
        Feeder("Feeder-4", n_blocks=40),
    ])
    p_limit_kw: float = P_LIMIT_KW
    p_emergency_kw: float = P_EMERGENCY_KW
    p_rated_kw: float = P_RATED_KW  
    transformer_mva: float = TRANSFORMER_MVA
    thermal_model: TransformerThermalModel = field(default_factory=lambda: TransformerThermalModel(
        theta_max=THETA_MAX,
        s_rated_kva=TRANSFORMER_KVA
    ))

    @property
    def n_blocks(self) -> int:
        return sum(f.n_blocks for f in self.feeders)

    @property
    def n_units(self) -> int:
        return self.n_blocks * N_UNITS_PER_BLOCK

    def check_constraint(self, p_total_kw: float, ambient_c: float | None = None) -> dict:
        """
        Return constraint status dict.
        - 'ok'    : θ_H ≤ θ_max (or P ≤ 20 MW if no thermal model)
        - 'amber' : θ_max < θ_H ≤ θ_emergency
        - 'red'   : θ_H > θ_emergency (or P > emergency rating)
        """
        # If ambient is provided, use the thermal model steady-state limit
        limit_kw = self.p_limit_kw
        if ambient_c is not None:
            limit_kw = self.thermal_model.max_load_for_temp(ambient_c)

        if p_total_kw <= limit_kw:
            status = "ok"
        elif p_total_kw <= self.p_emergency_kw:
            status = "amber"
        else:
            status = "red"
        
        congestion_relief_kw = max(0.0, p_total_kw - limit_kw)
        
        res = {
            "p_total_kw": p_total_kw,
            "p_total_mw": round(p_total_kw / 1000, 2),
            "p_limit_kw": limit_kw,
            "status": status,
            "congestion_relief_kw": congestion_relief_kw,
            "loading_pct": 100 * p_total_kw / self.p_rated_kw,
        }
        
        if ambient_c is not None:
            res["theta_h_steady_state_c"] = self.thermal_model.steady_state(p_total_kw, ambient_c)
            
        return res

    def probabilistic_constraint_check(
        self, p_mean_kw: float, p_std_kw: float, ambient_c: float | None = None, epsilon: float = 0.05
    ) -> dict:
        """
        Eq. (1) of the paper refined: P(theta_H > theta_max) > ε → congestion declared.
        
        If ambient_c is provided, identifies the power level P_crit such that 
        steady_state(P_crit, ambient_c) == theta_max, and checks P(P > P_crit) > ε.
        """
        limit_kw = self.p_limit_kw
        if ambient_c is not None:
            limit_kw = self.thermal_model.max_load_for_temp(ambient_c)

        if p_std_kw <= 1e-6:
            prob_exceed = 1.0 if p_mean_kw > limit_kw else 0.0
        else:
            from scipy.stats import norm
            prob_exceed = 1 - norm.cdf(limit_kw, loc=p_mean_kw, scale=p_std_kw)
            
        congested = prob_exceed > epsilon
        if p_std_kw <= 1e-6:
            relief_kw = max(0.0, p_mean_kw - limit_kw)
        else:
            z_score = norm.ppf(1 - epsilon)
            target_mean = limit_kw - (z_score * p_std_kw)
            relief_kw = max(0.0, p_mean_kw - target_mean)
            
        return {
            "p_mean_kw": p_mean_kw,
            "p_mean_mw": round(p_mean_kw / 1000, 2),
            "p_std_kw": p_std_kw,
            "P(exceed_thermal_limit)": round(float(prob_exceed), 4),
            "congested": congested,
            "congestion_relief_kw": relief_kw,
            "thermal_limit_kw": limit_kw,
            "ambient_c": ambient_c,
        }


NETWORK = MVNetwork()


if __name__ == "__main__":
    print(f"Network: {NETWORK.transformer_mva} MVA substation")
    print(f"  {NETWORK.n_blocks} residential blocks × {N_UNITS_PER_BLOCK} households "
          f"= {NETWORK.n_units:,} virtual customers")
    print(f"  P_rated={NETWORK.p_rated_kw/1000:.2f} MW  "
          f"P_LIMIT={NETWORK.p_limit_kw/1000:.1f} MW  "
          f"I_max={I_MAX_A:.0f} A @ {VOLTAGE_MV_KV} kV")
    for p in [15_000, 20_000, 25_000, 30_000]:
        r = NETWORK.check_constraint(p)
        print(f"  P={p/1000:.0f} MW → {r['status'].upper()}  "
              f"(loading={r['loading_pct']:.1f}%)")
