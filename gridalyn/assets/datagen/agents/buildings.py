"""Stochastic residential building thermal model.

Each building is an independent residential unit with:
  - 1st-order RC thermal model (thermostat-controlled electric baseboard)
  - Time-correlated AR(1) background load (appliances, lighting, hot water)
  - Stochastic parameters sampled at construction time to create diversity

Physical model (discrete-time, Δt = 1 min):
  T_in[k+1] = T_in[k] + (Δt/C) * ((T_out[k] - T_in[k])/R + η * P_heat[k])

Thermostat: ON/OFF hysteresis band around setpoint T_set ± deadband/2

**Deliberately independent of `gridalyn.assets.modeling.synthesis`'s
per-archetype `heating_kw_per_m2`/`cooling_kw_per_m2` capacity constants
(R27/Phase 32, 2026-08-20).** The two answer different questions and were
never meant to agree: this module is a *dynamic time-domain simulator* --
`P_HEAT_MAX_KW`/`R_MEAN`/etc. drive a stateful RC thermal model that produces
minute-by-minute load curves consumed by studies with pinned regression
baselines (e.g. `admm_thermal_consensus`'s heating agents); `synthesis.py`'s
archetype constants are a *static capacity lookup* used to populate
`device_registry.parquet`/`building_models.parquet` structural asset data,
with no time dimension at all. Reconciling them would mean either driving a
stateful simulator from a static lookup table or vice versa -- a real design
decision with regression-baseline risk for any study built on this module,
out of scope for a coherence pass. If you are looking to change either
model's capacity constants, check whether the other one should move too;
if you are looking to unify them, that is a separate, deliberate phase.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

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
R_MEAN = 11.0  # °C/kW  (R_house)
R_STD = 2.0  # ±18%
C_MEAN = 2.0  # kWh/°C (Fast indoor air mass constraint for realistic duty cycles)
C_STD = 0.5
P_HEAT_MAX_KW = 8.0  # kW
P_COOL_MAX_KW = 3.0  # kW
ETA_HEAT = 1.0  # electric baseboard: 100% conversion
ETA_COOL = 3.0  # A/C COP

# Background load statistics strictly used for thermal bounding (generation handled externally)
BG_MEAN_KW = 1.5  # kW/household
BG_STD_KW = 0.6

T_SET = 21.0
DEADBAND = 0.8  # ±0.4°C for heating

# Independent per-room thermostats in a Québec all-electric dwelling. Each zone
# latches ON/OFF around its own setpoint, so the house total steps rather than
# glides. Measured against the Hydro-Québec 1000-home set (all-electric subset,
# n=215): real heating moves >2 kW between consecutive 15-min steps in 39.9% of
# intervals and cycles with a ~83 min median period. See ``control="hysteresis"``.
N_ZONES_MIN = 3
N_ZONES_MAX = 6
ZONE_SETPOINT_SPREAD_C = 1.2
# Per-zone deadband. Kept at the whole-house DEADBAND: widening it to 1.25 °C
# was tried to slow the cycle toward the measured ~83 min and did not -- the
# crossing rate of the house total is set by the zone count, not the band --
# while it pushed the swing from 5.5 to 6.6 kW against a measured 4.6.
ZONE_DEADBAND_C = DEADBAND
T_COOL_SET = 24.0  # A/C setpoint
COOL_DEADBAND = 1.0  # ±0.5°C for cooling

DT_MIN = 1  # simulation time step in minutes
DT_H = DT_MIN / 60.0


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
    R: float = field(init=False)  # °C/kW
    C: float = field(init=False)  # kWh/°C
    p_heat_max: float = field(init=False)  # kW
    bg_mean: float = field(init=False)  # kW
    bg_std: float = field(init=False)  # kW
    occupancy_offset_min: int = field(init=False)  # phase shift for occupancy

    # State
    T_in: float = field(init=False)  # indoor temperature °C
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
        # Per-zone thermostats, consulted only when control="hysteresis".
        # Drawn from a SEPARATE stream keyed on unit_id: sampling them from
        # ``self.rng`` would shift every subsequent draw and silently change the
        # default path's initial conditions, and with them every frozen baseline.
        zrng = np.random.default_rng(0xB0A5 + int(self.unit_id))
        self.n_zones = int(zrng.integers(N_ZONES_MIN, N_ZONES_MAX + 1))
        self.zone_setpoints = np.sort(
            T_SET
            + zrng.uniform(
                -ZONE_SETPOINT_SPREAD_C / 2, ZONE_SETPOINT_SPREAD_C / 2, self.n_zones
            )
        )
        self.zone_share = zrng.dirichlet(np.full(self.n_zones, 6.0))
        self.zone_on = zrng.random(self.n_zones) < 0.5
        # Each zone carries its OWN air temperature. Sharing a single node was
        # the reason a first hysteresis attempt still glided: zones that sense
        # the same T_in latch almost together and the ensemble degenerates into
        # a slow proportional law (181 min cycle vs the measured 83 min). With
        # independent states each room cycles on its own dynamics and random
        # phase, which is what makes the house total step.
        self.zone_T = self.T_in + zrng.uniform(
            -ZONE_DEADBAND_C / 2, ZONE_DEADBAND_C / 2, self.n_zones
        )

    # Non-HVAC loads are injected externally by the ARX background generator so
    # this object can focus on the thermostat and envelope dynamics.

    def step(
        self,
        t_out: float,
        minute_of_day: float,
        p_bg_kw: float,
        p_cap_kw: float | None = None,
        dt_min: float = 1.0,
        integrator: str = "euler",
        control: str = "proportional",
    ) -> dict:
        """
        Advance one simulation step by dt_min minutes.

        Parameters
        ----------
        t_out        : outdoor temperature (°C)
        minute_of_day: float [0, 1439]
        p_bg_kw      : rigorously precalculated exact ARX background appliance
                       trace for this instant
        p_cap_kw     : if not None, total building power cap (CLS active)
        dt_min       : time step in minutes
        integrator   : thermal-update scheme; ``"euler"`` (default) keeps the
                       byte-identical forward-Euler update, ``"exact"`` opts into
                       the exact-discrete RC update. Any other value raises a
                       located ``ValueError``.

        Returns
        -------
        dict with p_total, p_heat, p_cool, p_bg, T_in
        """
        if control not in ("proportional", "hysteresis"):
            raise ValueError(
                f"Building.step: unsupported control {control!r}; allowed values "
                "are 'proportional' (default, the quantized 10-level controller "
                "that reproduces historical runs) and 'hysteresis' (independent "
                "per-zone thermostats that latch, the measured behaviour)."
            )
        if integrator not in ("euler", "exact"):
            raise ValueError(
                f"Building.step: unsupported integrator {integrator!r}; "
                "allowed values are 'euler' (default, forward-Euler) and "
                "'exact' (exact-discrete RC update)."
            )

        bg = max(float(p_bg_kw), 0.0)

        # ── 2.  Thermostat control (constant 21°C setpoint)
        # Night setback is not modeled here; setpoint diversity is represented
        # through stochastic initial states and building parameters.
        T_off = T_SET + DEADBAND / 2

        if control == "hysteresis":
            # Independent per-room thermostats, each latching around its own
            # setpoint. Latching is the whole point: a proportional law tracks
            # T_in continuously, so the house glides and never steps, while a
            # real dwelling swings >2 kW between consecutive 15-min samples in
            # ~40% of intervals with a ~83 min median cycle.
            on_below = self.zone_setpoints - ZONE_DEADBAND_C / 2.0
            off_above = self.zone_setpoints + ZONE_DEADBAND_C / 2.0
            # Each thermostat senses ITS OWN room, not the house mean.
            self.zone_on = np.where(
                self.zone_T <= on_below,
                True,
                np.where(self.zone_T >= off_above, False, self.zone_on),
            )
            p_heat_desired = float(
                self.p_heat_max * float(np.dot(self.zone_share, self.zone_on))
            )
            self.heating_on = bool(p_heat_desired > 0.0)
        else:
            # ── Discretized Proportional Controller (10 discrete baseboards)
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

        # ── 4.  Thermal dynamics
        if control == "hysteresis":
            # Per-zone first-order RC. Zone i owns share_i of the envelope, so
            # its capacitance and heater scale with the share and its resistance
            # inversely -- the zones in parallel reproduce the whole-house R, C
            # and p_heat_max exactly.
            share = self.zone_share
            c_z = self.C * share
            r_z = self.R / share
            p_z = self.p_heat_max * share * self.zone_on
            if p_cap_kw is not None and p_heat_desired > 0:
                p_z = p_z * (p_heat_actual / p_heat_desired)
            self.zone_T = self.zone_T + (dt_min / 60.0) / c_z * (
                (t_out - self.zone_T) / r_z + ETA_HEAT * p_z
            )
            self.T_in = float(np.dot(share, self.zone_T))
        elif integrator == "euler":
            # Forward-Euler update (default, byte-identical to historical runs).
            dT = (
                (dt_min / 60.0)
                / self.C
                * (
                    (t_out - self.T_in) / self.R
                    + ETA_HEAT * p_heat_actual
                    - ETA_COOL * p_cool_actual
                )
            )
            self.T_in += dT
        else:
            # Exact-discrete RC update: integrate the same continuous-time
            # dynamics dT/dt = (T_eq - T_in)/tau exactly over the step, where
            # tau = R*C (hours) and T_eq is the steady-state air temperature for
            # the held forcing. Unconditionally stable for large dt_min.
            tau = self.R * self.C
            dt_h = dt_min / 60.0
            t_eq = t_out + self.R * (
                ETA_HEAT * p_heat_actual - ETA_COOL * p_cool_actual
            )
            self.T_in += (1.0 - math.exp(-dt_h / tau)) * (t_eq - self.T_in)

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
