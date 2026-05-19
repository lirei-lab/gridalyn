"""
building.py – Stochastic building thermal model + background load.

Each building is an independent residential unit with:
  - 1st-order RC thermal model (thermostat-controlled electric baseboard)
  - Time-correlated AR(1) background load (appliances, lighting, hot water)
  - Stochastic parameters sampled at construction time to create diversity

Physical model (discrete-time, Δt = 1 min):
  T_in[k+1] = T_in[k] + (Δt/C) * ((T_out[k] - T_in[k])/R + η * P_heat[k])

Thermostat: ON/OFF hysteresis band around setpoint T_set ± deadband/2
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass, field


# ─────────────────────────────────────────────────────────────────────────────
# Household-level parameters (each Building object = one residential dwelling)
#
# Calibrated to Hydro-Québec/NRCan-style all-electric Québec dwellings:
#   Annual electricity:  ~20,000-22,000 kWh/yr/dwelling
#   Space heating share: ~55-60% -> ~12,000 kWh/yr/dwelling
#   Background load:      ~1.0-1.5 kW average (DHW, appliances, lighting)
#   Peak heat at -25°C:   ~6 kW/dwelling
#   Heating degree-days:  ~5,500 HDD18 (Trois-Rivières, QC)
#
#   Thermal resistance:
#     R = HDD * 24 h / E_heat = 5500 * 24 / 12000 ~= 11 °C/kW
#
#   Sanity check at T_out = -25°C:
#     Q_loss = (21 - -25) / 11 ~= 4.2 kW.
#     With stochastic capacity, thermostat cycling, DHW/appliances, and 3,235
#     dwellings, an aggregate winter peak near 18-19 MW is plausible for an
#     all-electric residential feeder.
# ─────────────────────────────────────────────────────────────────────────────
HOUSEHOLDS_PER_BUILDING = 1

# Thermal parameters (individual household air-node specific)
R_MEAN   = 11.0   # °C/kW  (R_house)
R_STD    = 2.0    # ±18%
C_MEAN   = 2.0    # kWh/°C (Fast indoor air mass constraint for realistic duty cycles)
C_STD    = 0.5
P_HEAT_MAX_KW = 8.0   # kW
P_COOL_MAX_KW = 3.0   # kW
ETA_HEAT      = 1.0     # electric baseboard: 100% conversion
ETA_COOL      = 3.0     # A/C COP

# Background load statistics strictly used for thermal bounding (generation handled externally)
BG_MEAN_KW     = 1.5    # kW/household
BG_STD_KW      = 0.6

T_SET      = 21.0
DEADBAND   = 0.8  # ±0.4°C for heating
T_COOL_SET = 24.0 # A/C setpoint
COOL_DEADBAND = 1.0 # ±0.5°C for cooling

DT_MIN         = 1     # simulation time step in minutes
DT_H           = DT_MIN / 60.0


@dataclass
class Building:
    """
    A single residential dwelling.

    Parameters are randomly sampled at initialisation to create natural
    diversity in the feeder population.
    """
    unit_id: int
    rng: np.random.Generator = field(default_factory=lambda: np.random.default_rng())

    # Physical parameters (sampled)
    R: float = field(init=False)   # °C/kW
    C: float = field(init=False)   # kWh/°C
    p_heat_max: float = field(init=False)    # kW
    bg_mean: float = field(init=False)       # kW
    bg_std: float = field(init=False)        # kW
    occupancy_offset_min: int = field(init=False)   # phase shift for occupancy

    # State
    T_in: float = field(init=False)    # indoor temperature °C
    heating_on: bool = False

    def __post_init__(self):
        self.R = float(self.rng.normal(R_MEAN, R_STD))
        self.C = float(self.rng.normal(C_MEAN, C_STD))
        self.R = max(self.R, R_MEAN * 0.3)
        self.C = max(self.C, C_MEAN * 0.3)
        # Wide distribution of capacities
        self.p_heat_max = float(self.rng.uniform(P_HEAT_MAX_KW * 0.4, P_HEAT_MAX_KW))
        self.p_cool_max = float(self.rng.uniform(P_COOL_MAX_KW * 0.4, P_COOL_MAX_KW))
        self.bg_mean = float(self.rng.normal(BG_MEAN_KW, BG_STD_KW))
        self.bg_mean = max(self.bg_mean, BG_MEAN_KW * 0.3)
        self.bg_std = float(self.rng.normal(BG_STD_KW, BG_STD_KW * 0.1))
        self.bg_std = max(self.bg_std, BG_STD_KW * 0.3)
        self.occupancy_offset_min = int(self.rng.integers(-30, 31))
        # Initial conditions: spread broadly so thermostat phases are uncorrelated
        # T_in sampled from [T_off - 3°C, T_off + 3°C] around setpoint
        # → some buildings start heating ON, others heating OFF, at random phases
        self.T_in = float(self.rng.uniform(17.0, 25.0))
        self.heating_on = self.T_in < (T_SET - DEADBAND / 2)
        self.cooling_on = self.T_in > (T_COOL_SET + COOL_DEADBAND / 2)

    # Non-HVAC loads are injected externally by the ARX background generator so
    # this object can focus on the thermostat and envelope dynamics.

    def step(
        self,
        t_out: float,
        minute_of_day: float,
        p_bg_kw: float,
        p_cap_kw: float | None = None,
        dt_min: float = 1.0,
    ) -> dict:
        """
        Advance one simulation step by dt_min minutes.

        Parameters
        ----------
        t_out        : outdoor temperature (°C)
        minute_of_day: float [0, 1439]
        p_bg_kw      : rigorously precalculated exact ARX background appliance trace for this instant
        p_cap_kw     : if not None, total building power cap (CLS active)
        dt_min       : time step in minutes

        Returns
        -------
        dict with p_total, p_heat, p_cool, p_bg, T_in
        """
        bg = max(float(p_bg_kw), 0.0)

        # ── 2.  Thermostat control (constant 21°C setpoint)
        # Night setback is not modeled here; setpoint diversity is represented
        # through stochastic initial states and building parameters.
        T_on  = T_SET - DEADBAND / 2
        T_off = T_SET + DEADBAND / 2

        # ── Discretized Proportional Controller (simulating 10 discrete baseboards)
        fraction_on = (T_off - self.T_in) / DEADBAND
        fraction_on = max(0.0, min(1.0, fraction_on))
        
        num_baseboards = 10.0
        fraction_quantized = round(fraction_on * num_baseboards) / num_baseboards
        
        p_heat_desired = fraction_quantized * self.p_heat_max
        self.heating_on = bool(p_heat_desired > 0)

        # ── 2b. A/C control
        T_c_on = T_COOL_SET + COOL_DEADBAND / 2
        T_c_off = T_COOL_SET - COOL_DEADBAND / 2
        
        if self.T_in >= T_c_on:
            self.cooling_on = True
        elif self.T_in <= T_c_off:
            self.cooling_on = False

        # Mutual exclusion
        if self.heating_on and self.cooling_on:
            self.cooling_on = False
            
        if not self.heating_on:
            p_heat_desired = 0.0
            
        p_cool_desired = self.p_cool_max if self.cooling_on else 0.0

        # ── 3.  Apply CLS power cap
        p_total_desired = p_heat_desired + p_cool_desired + bg
        if p_cap_kw is not None:
            p_total_allowed = min(p_total_desired, p_cap_kw)
            available_hvac = max(0.0, p_total_allowed - bg)
            p_heat_actual = min(p_heat_desired, available_hvac)
            p_cool_actual = min(p_cool_desired, available_hvac)
        else:
            p_total_allowed = p_total_desired
            p_heat_actual = p_heat_desired
            p_cool_actual = p_cool_desired

        # ── 4.  Thermal dynamics (Euler forward)
        dT = (dt_min / 60.0) / self.C * (
            (t_out - self.T_in) / self.R 
            + ETA_HEAT * p_heat_actual 
            - ETA_COOL * p_cool_actual
        )
        self.T_in += dT

        p_total_actual = p_heat_actual + p_cool_actual + bg
        return {
            "p_total_kw": p_total_actual,
            "p_heat_kw": p_heat_actual,
            "p_cool_kw": p_cool_actual,
            "p_bg_kw": bg,
            "T_in_C": self.T_in,
            "heating_on": self.heating_on,
            "cooling_on": self.cooling_on,
            "p_cap_kw": p_cap_kw,
        }
