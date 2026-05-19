"""
transformer_thermal.py – IEEE C57.91-2011 Transformer Thermal Model.

Implements the Clause 7 hottest-spot temperature model for mineral-oil-immersed
transformers. The model tracks two thermal states:

  1. Top-oil temperature rise (ΔΘ_TO) with time constant τ_TO (~180 min)
  2. Hottest-spot temperature rise (ΔΘ_HS) with time constant τ_HS (~8 min)

The hottest-spot temperature is:
    θ_H(t) = θ_ambient(t) + ΔΘ_TO(t) + ΔΘ_HS(t)

Constraint violation occurs when θ_H > θ_max (typically 120°C for normal ageing).

Reference: IEEE Std C57.91-2011, "Guide for Loading Mineral-Oil-Immersed
           Transformers and Step-Voltage Regulators," Clause 7.
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field


@dataclass
class TransformerThermalModel:
    """
    IEEE C57.91-2011 thermal model for a distribution/power transformer.

    Parameters (defaults for a typical 25 MVA ONAN distribution transformer)
    -------------------------------------------------------------------------
    s_rated_kva   : Rated apparent power (kVA)
    pf            : Power factor at rated load
    delta_theta_to_r : Rated top-oil temperature rise over ambient (°C)
    delta_theta_hs_r : Rated hottest-spot rise over top-oil (°C)
    tau_to_min    : Oil thermal time constant (minutes)
    tau_hs_min    : Winding thermal time constant (minutes)
    R             : Ratio of load losses to no-load losses at rated
    n             : Top-oil rise exponent (ONAN: 0.8, ONAF: 0.9, OFAF: 1.0)
    m             : Winding hottest-spot exponent (ONAN: 0.8, ONAF: 0.8)
    theta_max     : Maximum allowable hottest-spot temperature (°C)
    """
    s_rated_kva: float = 25_000.0       # 25 MVA
    pf: float = 0.95                     # nominal power factor
    delta_theta_to_r: float = 55.0       # °C, rated top-oil rise
    delta_theta_hs_r: float = 25.0       # °C, rated hottest-spot rise over top-oil
    tau_to_min: float = 180.0            # minutes, oil time constant
    tau_hs_min: float = 8.0              # minutes, winding time constant
    R: float = 5.0                       # load-loss to no-load-loss ratio
    n: float = 0.8                       # top-oil exponent (ONAN)
    m: float = 0.8                       # winding exponent (ONAN)
    theta_max: float = 120.0             # °C, maximum hot-spot temperature

    # Internal thermal state
    _delta_theta_to: float = field(default=0.0, init=False, repr=False)
    _delta_theta_hs: float = field(default=0.0, init=False, repr=False)

    @property
    def p_rated_kw(self) -> float:
        """Rated active power (kW)."""
        return self.s_rated_kva * self.pf

    def reset(self, ambient_c: float = 20.0, load_kw: float = 0.0):
        """Initialize thermal state to steady-state at given load and ambient."""
        K = load_kw / self.p_rated_kw if self.p_rated_kw > 0 else 0.0
        self._delta_theta_to = self._ultimate_top_oil_rise(K)
        self._delta_theta_hs = self._ultimate_hs_rise(K)

    def _ultimate_top_oil_rise(self, K: float) -> float:
        """
        Steady-state top-oil rise for load ratio K:
            ΔΘ_TO,U = ΔΘ_TO,R × [(K²·R + 1) / (R + 1)]^n
        """
        numerator = K ** 2 * self.R + 1.0
        denominator = self.R + 1.0
        return self.delta_theta_to_r * (numerator / denominator) ** self.n

    def _ultimate_hs_rise(self, K: float) -> float:
        """
        Steady-state hottest-spot rise over top-oil for load ratio K:
            ΔΘ_HS,U = ΔΘ_HS,R × K^(2m)
        """
        return self.delta_theta_hs_r * K ** (2 * self.m)

    def step(self, load_kw: float, ambient_c: float, dt_min: float = 1.0) -> float:
        """
        Advance the thermal model by dt_min minutes under given load and ambient.

        Uses the exponential approach to ultimate (Clause 7):
            ΔΘ(t+Δt) = ΔΘ_U + (ΔΘ(t) - ΔΘ_U) × exp(-Δt/τ)

        Parameters
        ----------
        load_kw   : active power load (kW)
        ambient_c : ambient temperature (°C)
        dt_min    : timestep in minutes

        Returns
        -------
        theta_h : hottest-spot temperature (°C)
        """
        K = max(0.0, load_kw / self.p_rated_kw) if self.p_rated_kw > 0 else 0.0

        # Ultimate (steady-state) values for current load
        delta_to_u = self._ultimate_top_oil_rise(K)
        delta_hs_u = self._ultimate_hs_rise(K)

        # Exponential approach to ultimate
        exp_to = np.exp(-dt_min / self.tau_to_min)
        exp_hs = np.exp(-dt_min / self.tau_hs_min)

        self._delta_theta_to = delta_to_u + (self._delta_theta_to - delta_to_u) * exp_to
        self._delta_theta_hs = delta_hs_u + (self._delta_theta_hs - delta_hs_u) * exp_hs

        theta_h = ambient_c + self._delta_theta_to + self._delta_theta_hs
        return float(theta_h)

    def steady_state(self, load_kw: float, ambient_c: float) -> float:
        """
        Equilibrium hottest-spot temperature at given load and ambient.
            θ_H = θ_ambient + ΔΘ_TO,U(K) + ΔΘ_HS,U(K)
        """
        K = max(0.0, load_kw / self.p_rated_kw) if self.p_rated_kw > 0 else 0.0
        return ambient_c + self._ultimate_top_oil_rise(K) + self._ultimate_hs_rise(K)

    def max_load_for_temp(self, ambient_c: float, theta_max: float | None = None) -> float:
        """
        Find the maximum sustained load (kW) that keeps θ_H ≤ θ_max
        at a given ambient temperature (steady-state).

        Uses bisection over load ratio K ∈ [0, 2.0].
        """
        if theta_max is None:
            theta_max = self.theta_max

        k_lo, k_hi = 0.0, 2.0
        for _ in range(50):
            k_mid = (k_lo + k_hi) / 2.0
            p_mid = k_mid * self.p_rated_kw
            theta = self.steady_state(p_mid, ambient_c)
            if theta > theta_max:
                k_hi = k_mid
            else:
                k_lo = k_mid

        return k_lo * self.p_rated_kw

    def simulate_profile(
        self,
        load_profile_kw: np.ndarray,
        ambient_profile_c: np.ndarray,
        dt_min: float = 1.0,
        initial_load_kw: float | None = None,
        initial_ambient_c: float | None = None,
    ) -> np.ndarray:
        """
        Simulate θ_H over a load + ambient profile.

        Parameters
        ----------
        load_profile_kw    : array of load values (kW), one per timestep
        ambient_profile_c  : array of ambient temperatures (°C), same length
        dt_min             : timestep in minutes
        initial_load_kw    : initial steady-state load for warm-up (default: first value)
        initial_ambient_c  : initial ambient (default: first value)

        Returns
        -------
        theta_h_profile : array of hottest-spot temperatures (°C)
        """
        n = len(load_profile_kw)
        assert len(ambient_profile_c) == n, "Load and ambient profiles must have same length"

        # Initialize to steady-state at the starting conditions
        init_load = initial_load_kw if initial_load_kw is not None else load_profile_kw[0]
        init_amb = initial_ambient_c if initial_ambient_c is not None else ambient_profile_c[0]
        self.reset(init_amb, init_load)

        theta_h = np.zeros(n)
        for i in range(n):
            theta_h[i] = self.step(load_profile_kw[i], ambient_profile_c[i], dt_min)

        return theta_h


# Default instance matching the 25 MVA substation in the case study
TRANSFORMER_THERMAL = TransformerThermalModel()


if __name__ == "__main__":
    model = TransformerThermalModel()
    print(f"Transformer: {model.s_rated_kva/1000:.0f} MVA, "
          f"P_rated={model.p_rated_kw/1000:.1f} MW")
    print(f"Thermal limits: θ_max={model.theta_max}°C")
    print(f"Time constants: τ_TO={model.tau_to_min} min, τ_HS={model.tau_hs_min} min")
    print()

    # Steady-state at various loads and ambient temperatures
    for amb in [-20, -10, 0, 10, 20, 30]:
        p_max = model.max_load_for_temp(amb) / 1000
        theta_at_rated = model.steady_state(model.p_rated_kw, amb)
        print(f"  Ambient={amb:+3d}°C → θ_H@rated={theta_at_rated:.1f}°C  "
              f"P_max(θ_H≤{model.theta_max}°C)={p_max:.2f} MW")
