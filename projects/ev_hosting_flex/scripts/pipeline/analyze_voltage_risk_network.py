"""Probabilistic full-net voltage-risk DIAGNOSTIC (LV undervoltage of the network).

The full-network sibling of validate_powerflow: it probabilizes the deterministic
network-wide LV undervoltage (0.916 pu at 1 EV/home). Loads the cached twin,
applies size_network_to_load (the HQ-sized net), then Monte-Carlos the EV fleet
across the cold days and the adoption grid. Each (draw x cold day x level) builds
a per-load kW vector (each home carries the diversified per-home base of ITS
cluster size + a uniform EV overlay), takes the network coincident-peak hour, and
solves ONE full-net AC (lightsim warm), recording the network-wide min LV bus
voltage. P(min V < CSA 0.917) + the low-voltage tail + the first-risk adoption. No
flexibility. Out of scope: phase imbalance (covered), clustered adoption (covered),
the deep-feeder residual held by LTC/regulators.
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
from pathlib import Path
from typing import Any

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from projects.ev_hosting_flex.scripts._annual import (  # noqa: E402
    aggregate_to_hourly,
    annual_base_realization,
    day_mean_temps,
    ev_fleet_annual,
    load_annual_tmy,
    tmy_hour_of_day,
)
from projects.ev_hosting_flex.scripts._powerflow import (  # noqa: E402
    network_min_voltage,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    COLD_DAY_TMEAN_C,
    DTYPE,
    PROJECT_OUTPUTS_DIR,
    ROUND_DECIMALS,
    SEED,
    VOLTAGE_EV_GRID,
    VOLTAGE_LIMITS_PU,
    VOLTAGE_NET_EV_POOL,
    VOLTAGE_NET_MC_DRAWS,
    VOLTAGE_RISK_THRESHOLD,
)
from projects.ev_hosting_flex.scripts.pipeline.analyze_voltage_risk import (  # noqa: E402
    _interp_first_cross,
)


def _adoption_network_voltage_stats(
    net: Any,
    per_load_base_annual: np.ndarray,
    evbar_pools: list[np.ndarray],
    cold_days: list[int],
    n_homes_total: int,
    ev_per_home: float,
    csa: float,
) -> dict[str, Any]:
    """Network min-LV-voltage population over (EV draw x cold day) at adoption
    ``ev_per_home``; returns P(undervoltage), the low tail, and the LV bus that
    holds the population minimum (for the where-it-binds diagnostic).

    Each home carries the per-home base of its cluster size (row of
    ``per_load_base_annual``) plus ``ev_per_home`` * the draw's mean single-EV
    profile; the network coincident-peak hour is taken per day, one full-net AC
    solved there.
    """
    lv_buses = net.bus.index[net.bus["vn_kv"] < 1.0]
    minvs: list[float] = []
    worst_v = 2.0
    worst_bus = -1
    for evbar in evbar_pools:
        for d in cold_days:
            sl = slice(d * 24, (d + 1) * 24)
            base_day = per_load_base_annual[:, sl]              # (n_load, 24)
            ev_day = float(ev_per_home) * np.asarray(evbar[sl], dtype=DTYPE)
            total_by_hour = base_day.sum(axis=0) + n_homes_total * ev_day
            h = int(np.argmax(total_by_hour))
            p_load = (base_day[:, h] + ev_day[h]).astype(DTYPE)  # (n_load,)
            mv = network_min_voltage(net, p_load)
            minvs.append(mv)
            if mv < worst_v:
                worst_v = mv
                worst_bus = int(net.res_bus.loc[lv_buses, "vm_pu"].idxmin())
    arr = np.array(minvs, dtype=DTYPE)
    return {
        "p_undervolt": round(float((arr < csa).mean()), ROUND_DECIMALS),
        "min_v_p50": round(float(np.percentile(arr, 50)), ROUND_DECIMALS),
        "min_v_p05": round(float(np.percentile(arr, 5)), ROUND_DECIMALS),
        "min_v_p01": round(float(np.percentile(arr, 1)), ROUND_DECIMALS),
        "min_v_worst": round(float(arr.min()), ROUND_DECIMALS),
        "worst_bus": worst_bus,
    }


def _sweep_network(
    net: Any,
    per_load_base_annual: np.ndarray,
    evbar_pools: list[np.ndarray],
    cold_days: list[int],
    n_homes_total: int,
    ev_grid: list[float],
    csa: float,
) -> dict[str, Any]:
    """Run `_adoption_network_voltage_stats` across the adoption grid; returns
    the five per-EV metric lists plus the per-level worst bus."""
    keys = ("p_undervolt", "min_v_p50", "min_v_p05", "min_v_p01", "min_v_worst")
    out: dict[str, list[Any]] = {k: [] for k in keys}
    out["worst_bus"] = []
    for e in ev_grid:
        s = _adoption_network_voltage_stats(
            net, per_load_base_annual, evbar_pools, cold_days,
            n_homes_total, e, csa,
        )
        for k in keys:
            out[k].append(s[k])
        out["worst_bus"].append(s["worst_bus"])
    return out
