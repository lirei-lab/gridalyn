"""Synthetic EV charger model with demand-response controls.

DR Program (HQ-style ILOUP / Rate Flex inspired):
  - Base tariff:             9.20 ¢/kWh
  - Off-peak rebate:        −1.50 ¢/kWh (received year-round outside CLS events)
  - CLS activation reward:   3.50 $/kW-h sustained curtailment
  - Max continuous CLS:      4 continuous hours per event
  - Max CLS events/year:    15 events
  - Penalty for breach:     18.40 ¢/kWh  (= 2 × base tariff)

Annual rebate calculation
─────────────────────────
The EV owner subscribes by agreeing to allow a power cap C_soft_i (kW) during
CLS events.  In return they receive a year-round off-peak charging rebate:

  Annual_Rebate [$] = C_soft_i [kW]
                      × rebate_rate [$/kW-h]
                      × non_peak_hours_year [h/yr]

  non_peak_hours_year ≈ 8760 − 15 events × 4 h/event = 8700 h/yr (approx)
  rebate_rate         = 0.015 $/kWh = 0.015 $/kW-h at nominal charging power

  → For a 7.2 kW L2 charger subscribing 5 kW of reserved curtailment:
      Annual_Rebate = 5 kW × 0.015 $/kW-h × 8700 h = $652.50/yr
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# ─────────────────────────────────────────────────────────────────────────────
# DR program constants (HQ Rate Flex / ILOUP analogues)
# ─────────────────────────────────────────────────────────────────────────────
BASE_TARIFF_PER_KWH = 0.0920  # $/kWh
OFFPEAK_REBATE_PER_KWH = 0.0150  # $/kWh  (year-round off-peak credit)
CLS_ACTIVATION_PER_KW_H = 3.50  # $/kW-h  (per kW curtailed, per hour active)
PENALTY_PER_KWH = 0.1840  # $/kWh  (breach penalty = 2× base)
MAX_CONTINUOUS_CLS_H = 4  # hours   (max single event duration)
MAX_EVENTS_PER_YEAR = 15  # events/year
PEAK_EVENTS_H_PER_YEAR = MAX_EVENTS_PER_YEAR * MAX_CONTINUOUS_CLS_H  # 60 h
NON_PEAK_H_PER_YEAR = 8760 - PEAK_EVENTS_H_PER_YEAR  # 8700 h

# Charger levels
L1_KW = 1.44  # 120 V / 12 A
L2_KW = 7.20  # 240 V / 30 A
L2_MID_KW = 3.84  # 240 V / 16 A  (common HQ-compatible)


@dataclass
class EVCharger:
    """
    Block-level EV aggregator (represents a fleet of EV chargers in a 50-unit block).

    Parameters
    ----------
    unit_id      : ties to the host building block
    n_evs        : number of EVs in this block (varies with penetration scenario)
    charger_kw   : rated power per individual EV charger
    c_soft_kw    : reserved curtailment capacity bid for the full block fleet (kW)
    rng          : random number generator for stochastic arrival/SoC
    """

    unit_id: int
    n_evs: int = 10  # number of EVs in this block
    charger_kw: float = L2_MID_KW  # kW per individual EV (3.84 kW)
    c_soft_fraction: float = 0.40  # fraction of fleet power offered as flexibility
    battery_kwh: float = 60.0  # average battery size

    rng: np.random.Generator = field(default_factory=lambda: np.random.default_rng())
    macro_arrival_shift_h: float = 0.0
    macro_arrival_std_h: float = 1.0

    # Per-EV stochastic sessions (sampled once)
    _arrival_minutes: list = field(default_factory=list, init=False, repr=False)
    _departure_minutes: list = field(default_factory=list, init=False, repr=False)
    _initial_socs: list = field(default_factory=list, init=False, repr=False)
    _socs: list = field(default_factory=list, init=False, repr=False)
    _plugged: list = field(default_factory=list, init=False, repr=False)

    @property
    def fleet_charger_kw(self) -> float:
        """Total rated charging power of the block fleet."""
        return self.n_evs * self.charger_kw

    @property
    def c_soft_kw(self) -> float:
        """Reserved curtailment volume for the fleet."""
        return self.fleet_charger_kw * self.c_soft_fraction

    @property
    def p_cap_kw(self) -> float:
        """Absolute power cap for fleet when CLS is active."""
        return self.fleet_charger_kw - self.c_soft_kw

    def __post_init__(self):
        self._sample_sessions()

    def _sample_sessions(self):
        """Sample one charging session per EV in the block."""
        self._arrival_minutes = []
        self._departure_minutes = []
        self._initial_socs = []
        self._socs = []
        self._plugged = []
        for _ in range(self.n_evs):
            mean_arr = 18.0 + self.macro_arrival_shift_h
            arr_h = float(
                np.clip(self.rng.normal(mean_arr, self.macro_arrival_std_h), 14.0, 24.0)
            )
            dep_h = float(np.clip(self.rng.normal(7.5, 0.75), 6.0, 10.0))
            soc_init = float(self.rng.uniform(0.20, 0.70))
            self._arrival_minutes.append(int(arr_h * 60))
            self._departure_minutes.append(int(dep_h * 60) + 1440)
            self._initial_socs.append(soc_init)
            self._socs.append(soc_init)
            self._plugged.append(False)

    def step(
        self,
        minute: int,
        cls_active: bool = False,
        dynamic_p_cap_kw: float | None = None,
        dt: int = 1,
    ) -> dict:
        """
        Advance one time step for all EVs in the block.
        Returns aggregate fleet charging power.

        Args:
            minute: Current time in absolute minutes from simulation start, or absolute minutes.
            dt: Timestep size in minutes (default 1). Arrival/departure
                triggers fire if the event falls in [minute, minute+dt).
        """
        p_fleet = 0.0
        minute_of_day = minute % 1440

        for idx in range(self.n_evs):
            # Arrival / departure — trigger if event falls within this step window
            arr = self._arrival_minutes[idx]
            dep = self._departure_minutes[idx] % 1440

            # Check if arrival falls within the current dt window (modulo 1440)
            # We handle the case where the window might straddle midnight,
            # though with 5-min dt and arrivals at ~18:00 it's fine.
            if arr >= minute_of_day and arr < minute_of_day + dt:
                self._plugged[idx] = True
                self._socs[idx] = self._initial_socs[idx]

            # Check if departure falls within the current dt window
            if dep >= minute_of_day and dep < minute_of_day + dt and self._plugged[idx]:
                self._plugged[idx] = False

            if not self._plugged[idx]:
                continue

            energy_needed = (1.0 - self._socs[idx]) * self.battery_kwh

            # Compute remaining time in minutes until departure
            t_remain = (dep - minute_of_day) % 1440
            if t_remain == 0:
                t_remain = 1440  # If exactly at departure time, avoid 0

            p_needed = energy_needed / (t_remain / 60.0)

            if cls_active and dynamic_p_cap_kw is not None:
                p_max = dynamic_p_cap_kw / self.n_evs
            else:
                p_max = self.charger_kw

            p_charge = max(0.0, min(p_needed, p_max, self.charger_kw))
            energy = p_charge * (dt / 60.0)
            self._socs[idx] = min(1.0, self._socs[idx] + energy / self.battery_kwh)
            p_fleet += p_charge

        return {
            "p_ev_kw": p_fleet,
            "n_plugged": sum(self._plugged),
            "cls_active": cls_active,
        }


def compute_annual_rebate(c_soft_kw: float) -> dict:
    """
    Compute the year-round off-peak rebate for subscribing c_soft_kw of
    curtailment capacity to the DR/CLS program.

    The subscriber receives OFFPEAK_REBATE_PER_KWH on all their charging
    outside CLS events, applied proportional to their subscribed capacity.

    Returns
    -------
    dict with rebate components
    """
    # Off-peak rebate: you save on every kWh of charging at rebated hours
    # Approximation: charger draws ~c_soft_kw on average during plugged hours
    # Average plugged hours/day ≈ 10 h (18:00 → 07:30)
    plugged_h_per_year = 10 * 365  # 3650 h/yr approximate
    non_peak_plugged_h = plugged_h_per_year - PEAK_EVENTS_H_PER_YEAR
    annual_energy_non_peak_kwh = c_soft_kw * non_peak_plugged_h
    offpeak_rebate = annual_energy_non_peak_kwh * OFFPEAK_REBATE_PER_KWH

    # CLS activation reward (when dispatched)
    max_cls_reward = (
        c_soft_kw * CLS_ACTIVATION_PER_KW_H * MAX_EVENTS_PER_YEAR * MAX_CONTINUOUS_CLS_H
    )

    return {
        "c_soft_kw": c_soft_kw,
        "non_peak_plugged_h_yr": non_peak_plugged_h,
        "annual_energy_non_peak_kwh": annual_energy_non_peak_kwh,
        "offpeak_rebate_$/yr": offpeak_rebate,
        "max_cls_activation_reward_$/yr": max_cls_reward,
        "total_max_benefit_$/yr": offpeak_rebate + max_cls_reward,
    }


def make_ev_chargers(
    n: int,
    n_evs_per_block: int = 10,
    charger_kw: float = L2_MID_KW,
    c_soft_fraction: float = 0.65,
    seed: int = 100,
    macro_arrival_shift_h: float = 0.0,
    macro_arrival_std_h: float = 1.0,
) -> list[EVCharger]:
    """
    Construct n EVCharger block-aggregators.

    Parameters
    ----------
    n                : number of residential blocks
    n_evs_per_block  : EVs per block (scales with penetration scenario)
    charger_kw       : rated power per individual EV charger (kW)
    c_soft_fraction  : fraction of total fleet power offered as CLS flexibility
    seed             : RNG seed for reproducibility
    macro_arrival_shift_h : global shift applied to average arrival times for the scenario
    macro_arrival_std_h   : spread of arrival times around the shifted mean
    """
    if n_evs_per_block == 0:
        return []
    rngs = [np.random.default_rng(seed + i * 7) for i in range(n)]
    return [
        EVCharger(
            unit_id=i,
            n_evs=n_evs_per_block,
            charger_kw=charger_kw,
            c_soft_fraction=c_soft_fraction,
            battery_kwh=float(rngs[i].uniform(40, 80)),
            rng=rngs[i],
            macro_arrival_shift_h=macro_arrival_shift_h,
            macro_arrival_std_h=macro_arrival_std_h,
        )
        for i in range(n)
    ]


if __name__ == "__main__":
    print("─── DR Program Annual Rebate Calculator ───")
    for kw in [1.44, 2.5, 3.84, 7.20]:
        r = compute_annual_rebate(kw)
        print(
            f"  c_soft={kw:.2f} kW → "
            f"Off-peak rebate ${r['offpeak_rebate_$/yr']:.0f}/yr  |  "
            f"Max CLS reward ${r['max_cls_activation_reward_$/yr']:.0f}/yr  |  "
            f"Total ${r['total_max_benefit_$/yr']:.0f}/yr"
        )


CHARGER_MIX_L2 = {7.2: 0.75, 9.6: 0.20, 11.5: 0.05}
"""Residential L2 charger population (kW -> share), MDPI-calibrated."""


def make_cold_coupled_ev_fleet(
    rng: np.random.Generator,
    n_evs: int,
    temp_series: pd.Series,
    *,
    res_minutes: int = 15,
    charger_mix: dict[float, float] | None = None,
    plugin_base: float = 0.60,
    plugin_max: float = 0.85,
    plugin_kcold: float = 0.006,
    session_kwh_median: float = 8.0,
    session_kwh_sigma: float = 0.5,
    session_kwh_kcold: float = 0.0125,
    session_kwh_min: float = 1.0,
    arrival_mean_h: float = 18.0,
    arrival_std_h: float = 1.5,
    arrival_clip_h: tuple[float, float] = (16.0, 22.0),
    cold_ref_c: float = 15.0,
) -> np.ndarray:
    """Return a per-EV uncontrolled charging matrix ``(n_evs, n_steps)`` in kW.

    A **profile generator**, not an actuator: it answers "what does an
    unmanaged residential L2 fleet draw in a cold climate?". For a controllable
    charger with state of charge and curtailment caps, use :class:`EVCharger`.

    Per EV and per calendar day in the window: the day's cold intensity
    ``cp = max(0, cold_ref_c - T_mean)`` raises BOTH the plug-in probability and
    the median session energy; arrival is an evening Gaussian; the session then
    charges as a **block at the sampled charger's rated power** until its energy
    is delivered. Blocks are allocated to steps by exact minute overlap and each
    stored value is the step's AVERAGE kW (``occupied_fraction x charger_kw``),
    so ``sum(step_kW) * res_minutes / 60`` reproduces the session energy.

    Block charging is deliberate. Spreading a session evenly over the plugged
    window pre-flattens the very peak a flexibility study is trying to measure,
    which makes such a study circular.

    Setting ``plugin_kcold=0`` and ``session_kwh_kcold=0`` yields the
    cold-agnostic counterfactual used by hosting studies that ignore weather.

    Args:
        rng: Pinned generator; fixed draw order per (EV, day) is
            plug-in -> charger -> energy -> arrival.
        n_evs: Fleet size (matrix rows; row order is the draw order, so row
            prefixes are valid sub-fleets).
        temp_series: Outdoor temperature with a monotonically increasing
            **local-time** ``DatetimeIndex`` covering the window. Calendar days
            and arrival clock hours are read from this index, so no phase anchor
            is passed. Resampled to ``res_minutes`` internally.
        res_minutes: Step width in minutes; must divide 1440.
        charger_mix: Charger power (kW) -> share; defaults to
            :data:`CHARGER_MIX_L2`. Shares are normalised.
        plugin_base: Plug-in probability on a mild day.
        plugin_max: Plug-in probability ceiling. Never binds below
            ``plugin_base``, so a caller-supplied floor above the default
            ceiling still takes effect.
        plugin_kcold: Plug-in cold slope (per degree of cold intensity).
        session_kwh_median: Median session energy on a mild day (kWh).
        session_kwh_sigma: Lognormal shape of the session energy.
        session_kwh_kcold: Session-energy cold slope.
        session_kwh_min: Floor on the sampled session energy (kWh).
        arrival_mean_h: Mean arrival, local clock hour.
        arrival_std_h: Arrival standard deviation in hours.
        arrival_clip_h: ``(low, high)`` clip on the arrival hour.
        cold_ref_c: Reference temperature for the cold intensity.

    Returns:
        A ``(n_evs, n_steps)`` float64 matrix in kW, where ``n_steps`` matches
        ``temp_series`` resampled to ``res_minutes``. Sessions running past the
        window end are truncated at the boundary.

    Raises:
        ValueError: If ``res_minutes`` does not divide 1440.
    """
    res = int(res_minutes)
    if res <= 0 or 1440 % res != 0:
        raise ValueError(
            f"res_minutes={res_minutes} must be a positive divisor of 1440 "
            f"(got remainder {1440 % res if res > 0 else 'n/a'}); "
            f"use 1, 5, 15, 30 or 60."
        )

    mix = dict(CHARGER_MIX_L2 if charger_mix is None else charger_mix)
    chargers = np.array(sorted(mix), dtype=np.float64)
    shares = np.array([mix[kw] for kw in sorted(mix)], dtype=np.float64)
    shares = shares / shares.sum()

    t_res = temp_series.resample(f"{res}min").interpolate()
    index = t_res.index
    n_steps = int(len(index))
    start_ts = index[0]
    window_min = float(n_steps * res)

    day_mean = t_res.groupby(index.normalize()).mean()
    cp_by_day = np.maximum(0.0, float(cold_ref_c) - day_mean.to_numpy(dtype=np.float64))
    day_starts = [(day - start_ts).total_seconds() / 60.0 for day in day_mean.index]

    lo, hi = arrival_clip_h
    demand = np.zeros((int(n_evs), n_steps), dtype=np.float64)

    for ev in range(int(n_evs)):
        for day_idx, day_start_m in enumerate(day_starts):
            cp = float(cp_by_day[day_idx])
            plug_ceiling = max(float(plugin_max), float(plugin_base))
            plug_p = min(plug_ceiling, float(plugin_base) + float(plugin_kcold) * cp)
            if rng.random() > plug_p:
                continue
            charger_kw = float(rng.choice(chargers, p=shares))
            median_kwh = float(session_kwh_median) * (
                1.0 + float(session_kwh_kcold) * cp
            )
            energy_kwh = max(
                float(session_kwh_min),
                float(rng.lognormal(np.log(median_kwh), float(session_kwh_sigma))),
            )
            arrival_h = float(
                np.clip(rng.normal(float(arrival_mean_h), float(arrival_std_h)), lo, hi)
            )
            start_m = day_start_m + arrival_h * 60.0
            end_m = start_m + energy_kwh / charger_kw * 60.0
            if end_m <= 0.0 or start_m >= window_min:
                continue
            first = int(np.floor(max(0.0, start_m) / res))
            last = int(np.ceil(min(window_min, end_m) / res))
            for slot in range(first, last):
                slot_start_m = float(slot * res)
                overlap_min = max(
                    0.0,
                    min(end_m, slot_start_m + res) - max(start_m, slot_start_m),
                )
                if overlap_min <= 0.0:
                    continue
                demand[ev, slot] += (overlap_min / res) * charger_kw
    return demand
