"""Deterministic design-day AC power-flow kernel for the validation stage.

Builds the per-home hourly load profiles (deterministic heating-degree base +
diversified coincident EV overlay), runs the cached pandapower twin hour by
hour per scenario, and counts CSA C235 voltage / thermal violations. Pure
functions over numpy/pandas; the governed wiring (cache paths, scenario matrix,
report) lives in ``pipeline/validate_powerflow.py``.

GUARD-02: no module-scope ``import pandapower`` — the solver import is deferred
inside :func:`run_design_day_powerflow` so cache-free unit tests of the profile
and violation helpers never pull the heavy dependency.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from projects.ev_hosting_flex.scripts.config import (
    BG_KW,
    CHARGING_WINDOW,
    DIVERSITY_FACTOR,
    DTYPE,
    EV_UNIT_KW,
    POWER_FACTOR,
    R_THERM,
    SLACK_VM_PU,
    T_BALANCE,
    VOLTAGE_LIMITS_PU,
)

N_DESIGN_HOURS = 24
"""Hourly step count of the design-day validation profiles."""


def design_day_hourly_temps() -> np.ndarray:
    """Return the design day's 24 hourly mean temperatures (°C, float64).

    Reuses the governed design-day seam (``_generators.select_design_day`` over
    the committed TMY — empirically 1990-01-19) and aggregates the native 1-min
    frame to hourly means, mirroring the MC kernel's aggregation step.

    Returns:
        A ``(24,)`` float64 array of hourly mean ``temp_air``.

    Raises:
        ValueError: If the selected design day does not aggregate to 24 hours.
    """
    from projects.ev_hosting_flex.scripts._generators import select_design_day

    day = select_design_day()
    hourly = day["temp_air"].resample("1h").mean().to_numpy(dtype=DTYPE)
    if hourly.shape != (N_DESIGN_HOURS,):
        raise ValueError(
            f"design_day_hourly_temps aggregated to shape {hourly.shape}, "
            f"expected ({N_DESIGN_HOURS},). Remediation: verify the committed "
            "TMY covers the full design day at 1-min resolution."
        )
    return hourly


def base_profile_per_home_kw(temps_c: np.ndarray) -> np.ndarray:
    """Return the deterministic per-home heating-degree base profile (kW).

    ``load(t) = max(0, T_BALANCE − T(t)) / R_THERM + BG_KW`` — the manuscript's
    deterministic design anchor (D-08; at −25 °C it reproduces the 6.5 kW/home
    ADMD). The stochastic Monte-Carlo base lives in stages 3–6; this layer is
    deliberately deterministic so the AC validation is reproducible without an
    ensemble.

    Args:
        temps_c: ``(24,)`` hourly temperatures in °C.

    Returns:
        A ``(24,)`` float64 per-home load profile in kW.
    """
    temps = np.asarray(temps_c, dtype=DTYPE)
    heating = np.maximum(0.0, (float(T_BALANCE) - temps)) / float(R_THERM)
    return (heating + float(BG_KW)).astype(DTYPE)


def ev_profile_per_home_kw(penetration: float) -> np.ndarray:
    """Return the diversified coincident per-home EV overlay profile (kW).

    ``penetration × EV_UNIT_KW × DIVERSITY_FACTOR`` (2.52 kW per EV coincident,
    D-05) applied flat inside the evening ``CHARGING_WINDOW`` (end-exclusive),
    zero elsewhere. Fractional penetrations scale linearly (the diversified
    aggregate view).

    Args:
        penetration: EVs per home (≥ 0; 0.0 returns the all-zero profile).

    Returns:
        A ``(24,)`` float64 per-home EV draw profile in kW.

    Raises:
        ValueError: If ``penetration`` is negative.
    """
    if penetration < 0.0:
        raise ValueError(
            f"ev_profile_per_home_kw received penetration={penetration}; the "
            "EV overlay is a physical draw and must be >= 0."
        )
    profile = np.zeros(N_DESIGN_HOURS, dtype=DTYPE)
    start, end = CHARGING_WINDOW
    coincident_kw = float(penetration) * float(EV_UNIT_KW) * float(DIVERSITY_FACTOR)
    profile[start:end] = coincident_kw
    return profile


def clip_to_headroom(
    ev_kw: np.ndarray, base_kw: np.ndarray, rating_kw: float
) -> np.ndarray:
    """Clip an aggregate EV profile to the transformer headroom, hour by hour.

    ``a(t) = min(ev(t), max(0, rating − base(t)))`` — the deferral/power-limiting
    mechanism ENVELOPE: by construction the composed feeder load never exceeds
    the rating, which is exactly what the AC validation needs to show the
    "after with flexibility" network state. Energy bookkeeping (carry-forward,
    unserved fractions) is the stages-5/6 kernels' job, not this layer's.

    Args:
        ev_kw: ``(24,)`` aggregate EV draw in kW.
        base_kw: ``(24,)`` aggregate base load in kW.
        rating_kw: Transformer usable rating in kW (> 0).

    Returns:
        A ``(24,)`` float64 clipped EV profile in kW.

    Raises:
        ValueError: If ``rating_kw`` is not positive.
    """
    if rating_kw <= 0.0:
        raise ValueError(
            f"clip_to_headroom received rating_kw={rating_kw}; the headroom "
            "clip needs a positive transformer rating."
        )
    ev = np.asarray(ev_kw, dtype=DTYPE)
    base = np.asarray(base_kw, dtype=DTYPE)
    headroom = np.maximum(0.0, float(rating_kw) - base)
    return np.minimum(ev, headroom).astype(DTYPE)


def run_design_day_powerflow(
    net: Any,
    p_kw_by_load: np.ndarray,
    *,
    slack_vm_pu: float = SLACK_VM_PU,
    power_factor: float = POWER_FACTOR,
) -> dict[str, pd.DataFrame]:
    """Run 24 hourly AC power flows and return the raw result tables.

    Args:
        net: Loaded pandapower net (mutated in place: load p/q, ext_grid vm).
        p_kw_by_load: ``(n_load, 24)`` float64 per-load active power in kW.
        slack_vm_pu: Slack (substation LTC) setpoint (D: ``SLACK_VM_PU``).
        power_factor: Constant lagging power factor for the Q injection.

    Returns:
        Dict of long-format DataFrames keyed ``bus_voltage`` (hour, bus,
        vm_pu), ``line_loading`` (hour, line, loading_percent) and
        ``trafo_loading`` (hour, trafo, loading_percent).

    Raises:
        ValueError: If the profile shape does not match the net's load table.
    """
    import pandapower as pp

    p_kw = np.asarray(p_kw_by_load, dtype=DTYPE)
    if p_kw.shape != (len(net.load), N_DESIGN_HOURS):
        raise ValueError(
            f"run_design_day_powerflow received p_kw_by_load {p_kw.shape}, "
            f"expected ({len(net.load)}, {N_DESIGN_HOURS}) for this net. "
            "Remediation: build one row per net.load in hour columns."
        )

    q_factor = float(np.tan(np.arccos(float(power_factor))))
    net.ext_grid["vm_pu"] = float(slack_vm_pu)

    frames: dict[str, list[pd.DataFrame]] = {
        "bus_voltage": [],
        "line_loading": [],
        "trafo_loading": [],
    }
    for hour in range(N_DESIGN_HOURS):
        net.load["p_mw"] = p_kw[:, hour] / 1000.0
        net.load["q_mvar"] = net.load["p_mw"] * q_factor
        pp.runpp(net, numba=True)
        frames["bus_voltage"].append(
            pd.DataFrame(
                {
                    "hour": hour,
                    "bus": net.res_bus.index.to_numpy(),
                    "vm_pu": net.res_bus["vm_pu"].to_numpy(dtype=DTYPE),
                }
            )
        )
        frames["line_loading"].append(
            pd.DataFrame(
                {
                    "hour": hour,
                    "line": net.res_line.index.to_numpy(),
                    "loading_percent": net.res_line["loading_percent"].to_numpy(
                        dtype=DTYPE
                    ),
                }
            )
        )
        frames["trafo_loading"].append(
            pd.DataFrame(
                {
                    "hour": hour,
                    "trafo": net.res_trafo.index.to_numpy(),
                    "loading_percent": net.res_trafo["loading_percent"].to_numpy(
                        dtype=DTYPE
                    ),
                }
            )
        )
    return {key: pd.concat(parts, ignore_index=True) for key, parts in frames.items()}


def count_violations(
    results: Mapping[str, pd.DataFrame],
    lv_bus_ids: np.ndarray,
    *,
    limits: Mapping[str, float] = VOLTAGE_LIMITS_PU,
) -> dict[str, Any]:
    """Classify a scenario's power-flow results against CSA + thermal limits.

    Voltage bands apply to LV buses only (the CSA C235 service-entrance bands
    on the 120 V base); thermal counts are network-wide. "n_*" counters count
    distinct ELEMENTS violating in at least one hour (a bus dipping low for
    three hours is one violating bus, not three).

    Args:
        results: Output of :func:`run_design_day_powerflow`.
        lv_bus_ids: Bus indices of the LV (240 V) level.
        limits: Voltage bands in pu (default: ``VOLTAGE_LIMITS_PU``).

    Returns:
        A flat dict of scenario violation metrics (floats/ints).
    """
    volt = results["bus_voltage"]
    lv = volt[volt["bus"].isin(np.asarray(lv_bus_ids))]
    lines = results["line_loading"]
    trafos = results["trafo_loading"]

    def _n_elements(frame: pd.DataFrame, key: str, mask: pd.Series) -> int:
        return int(frame.loc[mask, key].nunique())

    return {
        "min_lv_vm_pu": float(lv["vm_pu"].min()),
        "p05_lv_vm_pu": float(lv["vm_pu"].quantile(0.05)),
        "n_lv_buses_below_normal": _n_elements(
            lv, "bus", lv["vm_pu"] < float(limits["normal_low"])
        ),
        "n_lv_buses_below_extreme": _n_elements(
            lv, "bus", lv["vm_pu"] < float(limits["extreme_low"])
        ),
        "n_lv_buses_above_normal": _n_elements(
            lv, "bus", lv["vm_pu"] > float(limits["normal_high"])
        ),
        "max_line_loading_percent": float(lines["loading_percent"].max()),
        "n_lines_over_100": _n_elements(
            lines, "line", lines["loading_percent"] > 100.0
        ),
        "max_trafo_loading_percent": float(trafos["loading_percent"].max()),
        "n_trafos_over_100": _n_elements(
            trafos, "trafo", trafos["loading_percent"] > 100.0
        ),
    }
