"""Stochastic electric domestic-hot-water (DHW) tank fleet generator.

An explicit hot-water tank is what makes an all-electric cold-climate dwelling
realistic in ENERGY as well as in peak. Modelling hot water only as part of a
smooth background trace understates annual consumption and erases the
short, high-power reheat bursts that dominate a feeder's fine structure.

Validated against the CREST demand-model lineage; see
``projects/ev_hosting_flex/CALIBRATION.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

WATER_CP_KJ_PER_KG_K = 4.186


@dataclass(frozen=True)
class DHWTankParams:
    """Population parameters for a fleet of thermostatic hot-water tanks.

    Defaults describe a standard Québec all-electric installation: a 270 L
    (60 gal) tank with a 4.5 kW resistive element. The ``*_jitter`` fields give
    each home its own tank, which is what staggers the reheats so the aggregate
    has no coincident on/off step.

    Attributes:
        tank_l: Mean tank water volume (L).
        element_kw: Mean resistive element power (kW).
        t_set: Mean thermostat setpoint (deg C).
        t_low: Mean element cut-in temperature (deg C).
        t_amb: Indoor ambient around the tank (deg C).
        ua_kw_per_k: Standby heat-loss coefficient (kW/K).
        daily_l_mean: Mean daily hot-water draw per home (L).
        daily_l_std: Per-home daily-draw standard deviation (L).
        daily_l_min: Floor on the per-home daily draw (L).
        inlet_min_c: Cold-water inlet temperature in winter (deg C).
        inlet_max_c: Cold-water inlet temperature in summer (deg C).
        setpoint_jitter_c: Per-home setpoint standard deviation (deg C).
        deadband_jitter_c: Per-home deadband standard deviation (deg C).
        element_jitter_kw: Per-home element-power standard deviation (kW).
        tank_l_jitter_l: Per-home tank-volume standard deviation (L).
    """

    tank_l: float = 270.0
    element_kw: float = 4.5
    t_set: float = 60.0
    t_low: float = 53.0
    t_amb: float = 20.0
    ua_kw_per_k: float = 0.0025
    daily_l_mean: float = 180.0
    daily_l_std: float = 30.0
    daily_l_min: float = 60.0
    inlet_min_c: float = 10.0
    inlet_max_c: float = 15.0
    setpoint_jitter_c: float = 2.0
    deadband_jitter_c: float = 1.5
    element_jitter_kw: float = 0.5
    tank_l_jitter_l: float = 30.0


@dataclass(frozen=True)
class DHWDrawProfile:
    """Occupancy-driven hot-water draw shape over the local clock hour.

    A continuous all-day baseline plus smooth morning and evening Gaussian
    peaks. The baseline is deliberately non-zero: an hour of exactly zero draw
    lets every tank drift and then cut in together, which produces an aggregate
    switching step that stochastic aggregation should never show.

    Attributes:
        base_weight: All-day baseline draw weight.
        morning_hour: Morning occupancy peak (local hour).
        morning_sigma: Morning peak width (h).
        morning_amp: Morning peak amplitude.
        evening_hour: Evening occupancy peak (local hour).
        evening_sigma: Evening peak width (h).
        evening_amp: Evening peak amplitude.
    """

    base_weight: float = 0.15
    morning_hour: float = 7.0
    morning_sigma: float = 1.6
    morning_amp: float = 1.0
    evening_hour: float = 19.0
    evening_sigma: float = 2.2
    evening_amp: float = 1.3


def dhw_draw_profile(profile: DHWDrawProfile | None = None) -> np.ndarray:
    """Return the 24-hour normalised hot-water draw weights.

    Args:
        profile: Shape parameters; defaults to :class:`DHWDrawProfile`.

    Returns:
        A ``(24,)`` float64 array summing to 1, indexed by LOCAL clock hour.
    """
    cfg = profile if profile is not None else DHWDrawProfile()
    h = np.arange(24, dtype=np.float64)
    weights = (
        float(cfg.base_weight)
        + float(cfg.morning_amp)
        * np.exp(-0.5 * ((h - float(cfg.morning_hour)) / float(cfg.morning_sigma)) ** 2)
        + float(cfg.evening_amp)
        * np.exp(-0.5 * ((h - float(cfg.evening_hour)) / float(cfg.evening_sigma)) ** 2)
    )
    return (weights / weights.sum()).astype(np.float64)


def make_dhw_tank_fleet(
    rng: np.random.Generator,
    n_homes: int,
    temp_series: pd.Series,
    *,
    res_minutes: int = 15,
    params: DHWTankParams | None = None,
    profile: DHWDrawProfile | None = None,
) -> np.ndarray:
    """Return the feeder-aggregate DHW demand ``(n_steps,)`` in kW.

    Each home gets a single-node thermostatic tank with its own volume,
    element power, setpoint and deadband. Per step the draw removes hot water
    (``V*cp*(T - T_inlet)``), standby loses ``UA*(T - T_amb)``, and the element
    reheats toward the setpoint once ``T`` falls below the home's cut-in.

    Args:
        rng: Pinned generator; per home the draw order is
            daily volume -> setpoint -> deadband -> element -> tank volume.
        n_homes: Dwelling count; the return is the sum over homes.
        temp_series: Outdoor temperature with a **local-time**
            ``DatetimeIndex``. Drives the seasonal cold-water inlet, and its
            first timestamp anchors the draw profile to the local clock.
        res_minutes: Step width in minutes; must divide 1440.
        params: Tank population parameters; defaults to :class:`DHWTankParams`.
        profile: Draw shape; defaults to :class:`DHWDrawProfile`.

    Returns:
        A ``(n_steps,)`` float64 feeder-aggregate trace in kW, where
        ``n_steps`` matches ``temp_series`` resampled to ``res_minutes``.

    Raises:
        ValueError: If ``res_minutes`` does not divide 1440.
    """
    res = int(res_minutes)
    if res <= 0 or 1440 % res != 0:
        raise ValueError(
            f"res_minutes={res_minutes} must be a positive divisor of 1440; "
            f"use 1, 5, 15, 30 or 60."
        )

    cfg = params if params is not None else DHWTankParams()
    steps_per_hour = max(1, (24 * 60 // res) // 24)
    dt_h = res / 60.0

    # LOCAL-hour phase anchor: array position k is local clock hour
    # (hod0 + k // steps_per_hour) % 24. The draw weights are clock-hour keyed,
    # so they MUST be shifted by hod0 or the reheat peak lands hours early.
    hod0 = int(temp_series.index[0].hour)

    t_res = temp_series.resample(f"{res}min").interpolate().to_numpy(dtype=np.float64)
    n_steps = int(t_res.shape[0])
    inlet = float(cfg.inlet_min_c) + (
        float(cfg.inlet_max_c) - float(cfg.inlet_min_c)
    ) * np.clip((t_res + 20.0) / 50.0, 0.0, 1.0)

    weights = dhw_draw_profile(profile)
    base_deadband = float(cfg.t_set) - float(cfg.t_low)
    cp = WATER_CP_KJ_PER_KG_K

    feeder = np.zeros(n_steps, dtype=np.float64)
    for _ in range(int(n_homes)):
        daily_l = max(
            float(cfg.daily_l_min),
            float(rng.normal(cfg.daily_l_mean, cfg.daily_l_std)),
        )
        t_set = float(rng.normal(cfg.t_set, cfg.setpoint_jitter_c))
        deadband = max(1.0, float(rng.normal(base_deadband, cfg.deadband_jitter_c)))
        t_low = t_set - deadband
        element = max(1.0, float(rng.normal(cfg.element_kw, cfg.element_jitter_kw)))
        tank_l = max(100.0, float(rng.normal(cfg.tank_l, cfg.tank_l_jitter_l)))
        c_tank = tank_l * cp / 3600.0  # kWh/K
        tank = t_set
        for k in range(n_steps):
            hod = (hod0 + k // steps_per_hour) % 24
            exp_l = daily_l * float(weights[hod]) / steps_per_hour
            vol = float(rng.gamma(2.0, exp_l / 2.0)) if exp_l > 0.0 else 0.0
            e_draw = vol * cp * (tank - float(inlet[k])) / 3600.0
            e_loss = float(cfg.ua_kw_per_k) * (tank - float(cfg.t_amb)) * dt_h
            tank -= (e_draw + e_loss) / c_tank
            if tank < t_low:
                e_in = min(element * dt_h, c_tank * (t_set - tank))
                tank += e_in / c_tank
                feeder[k] += e_in / dt_h
    return feeder
