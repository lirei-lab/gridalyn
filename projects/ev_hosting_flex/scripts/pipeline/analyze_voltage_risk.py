"""Probabilistic voltage-risk DIAGNOSTIC (LV undervoltage, diagnosis first).

Estimates the probability and severity of LV undervoltage on the governed feeder
under EV adoption: Monte-Carlo the EV fleet across the cold days, solve one
balanced AC snapshot per (draw x cold day) at the coincident-peak hour, and
record the minimum LV bus voltage. P(min V < CSA 0.917) + the low voltage tail +
the first-risk adoption. No flexibility. Out of scope: phase imbalance (covered),
full-net AC (the governed feeder is the representative unit).
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
    day_mean_temps,
    ev_fleet_annual,
    load_annual_tmy,
    tmy_hour_of_day,
)
from projects.ev_hosting_flex.scripts._powerflow import (  # noqa: E402
    extract_feeder_subnet,
    feeder_min_voltage,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    COLD_DAY_TMEAN_C,
    DTYPE,
    PROJECT_OUTPUTS_DIR,
    ROUND_DECIMALS,
    SEED,
    SLACK_VM_PU,
    VOLTAGE_EV_GRID,
    VOLTAGE_LIMITS_PU,
    VOLTAGE_MC_DRAWS,
    VOLTAGE_RISK_THRESHOLD,
)


def _adoption_voltage_stats(
    subnet: Any,
    base_hourly: np.ndarray,
    pools: list[np.ndarray],
    cold_days: list[int],
    n_homes: int,
    ev_per_home: float,
    slack: float,
    csa: float,
) -> dict[str, float]:
    """Min-LV-voltage population over (EV draw x cold day) at adoption
    ``ev_per_home``; returns P(undervoltage) + the low voltage tail."""
    n_evs = int(round(float(ev_per_home) * int(n_homes)))
    minvs: list[float] = []
    for pool in pools:
        for d in cold_days:
            sl = slice(d * 24, (d + 1) * 24)
            base_day = np.asarray(base_hourly[sl], dtype=DTYPE)
            ev_day = (
                pool[:n_evs, sl].sum(axis=0) if n_evs > 0 else np.zeros(24, DTYPE)
            )
            total = base_day + ev_day
            per_home = float(total.max()) / int(n_homes)
            load_vec = np.full(int(n_homes), per_home, dtype=DTYPE)
            minvs.append(feeder_min_voltage(subnet, load_vec, slack_vm_pu=slack))
    arr = np.array(minvs, dtype=DTYPE)
    return {
        "p_undervolt": round(float((arr < csa).mean()), ROUND_DECIMALS),
        "min_v_p50": round(float(np.percentile(arr, 50)), ROUND_DECIMALS),
        "min_v_p05": round(float(np.percentile(arr, 5)), ROUND_DECIMALS),
        "min_v_p01": round(float(np.percentile(arr, 1)), ROUND_DECIMALS),
        "min_v_worst": round(float(arr.min()), ROUND_DECIMALS),
    }
