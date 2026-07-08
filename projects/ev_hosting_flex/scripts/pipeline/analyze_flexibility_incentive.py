"""Study 1A: the vanishing valley -> climate-adaptive flexibility incentive.

Bins the committed TMY year by daily-mean temperature and, per bin, dispatches
the fixed EV pool on the governed 6-home / 75 kVA feeder under three policies
(uncontrolled / valley-fill shift / curtail), taking the P95 evening loading
over the bin's days. A lognormal willingness-to-accept (WTA) participation model
turns the enrollment needed to host the target fleet into a required incentive;
the cheaper feasible policy wins each bin. The headline is the CROSSOVER
temperature where the optimal incentive migrates from a shift discount (warm,
a valley exists) to a curtailment payment (cold, no valley).

Pure-kW on the governed feeder (no pandapower); fully deterministic (fixed pool,
analytic WTA). The WTA curve is an illustrative behavioural assumption; the
crossover temperature is robust, the subsidy dollars are illustrative.
"""

from __future__ import annotations

import argparse
import json
import os
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
from scipy.special import ndtr, ndtri  # noqa: E402

from projects.ev_hosting_flex.scripts._annual import (  # noqa: E402
    aggregate_to_hourly,
    climate_bin_days,
    day_mean_temps,
    load_annual_tmy,
    tmy_hour_of_day,
    valley_fill_shift,
)
from projects.ev_hosting_flex.scripts._powerflow import (  # noqa: E402
    apply_local_curtailment,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    CLIMATE_BIN_EDGES,
    DTYPE,
    EVENING_WINDOW_ANNUAL,
    HOSTING_TARGET_EV_PER_HOME,
    POWER_FACTOR,
    PROJECT_OUTPUTS_DIR,
    ROUND_DECIMALS,
    TRANSFORMER_KVA,
    WTA_CURTAIL_MEDIAN,
    WTA_CURTAIL_SIGMA,
    WTA_SHIFT_MEDIAN,
    WTA_SHIFT_SIGMA,
)

_RATING_KW = float(TRANSFORMER_KVA) * float(POWER_FACTOR)


def wta_enrollment(incentive: float, median: float, sigma: float) -> float:
    """Fraction of owners enrolling at ``incentive`` (lognormal WTA CDF)."""
    if incentive <= 0.0:
        return 0.0
    return float(ndtr((np.log(incentive) - np.log(median)) / sigma))


def wta_price_for_enrollment(frac: float, median: float, sigma: float) -> float:
    """Incentive at which ``frac`` of owners enrol (lognormal WTA PPF)."""
    frac = min(max(float(frac), 1e-9), 1.0 - 1e-9)
    return float(median * np.exp(sigma * ndtri(frac)))


def _bin_p95_loading(
    *,
    base: np.ndarray,
    pool: np.ndarray,
    day_indices: list[int],
    n_ev: int,
    n_enrolled: int,
    policy: str,
    rating_kw: float,
    hod0: int,
    charger_kw: np.ndarray,
    evening: tuple[int, int],
) -> float:
    """P95 over the bin's days of the evening-window peak loading (% of rating).

    Args:
        base: ``(N_days*24,)`` hourly feeder base kW (array-index order).
        pool: ``(pool, N_days*24)`` hourly per-EV kW.
        day_indices: day indices belonging to the bin.
        n_ev: fleet size on the feeder (first ``n_ev`` pool rows).
        n_enrolled: flexible EVs (first ``n_enrolled`` of the fleet).
        policy: ``"uncontrolled" | "shift" | "curtail"``.
        rating_kw: feeder usable rating (kW).
        hod0: LOCAL hour of array index 0 (local-hour ordering via np.roll).
        charger_kw: ``(pool,)`` per-EV charger power (kW).
        evening: ``(start, end)`` LOCAL-hour evening window.

    Returns:
        The P95 (over the bin's days) evening peak loading, in percent.
    """
    start, end = evening
    peaks: list[float] = []
    for d in day_indices:
        sl = slice(d * 24, (d + 1) * 24)
        base_day = np.roll(np.asarray(base[sl], dtype=DTYPE), int(hod0))
        fleet = pool[:n_ev, sl]
        fleet = np.roll(fleet, int(hod0), axis=1)
        enrolled = fleet[:n_enrolled]
        free_agg = (
            fleet[n_enrolled:].sum(axis=0) if n_ev > n_enrolled else np.zeros(24, DTYPE)
        )
        if policy == "uncontrolled" or n_enrolled == 0:
            flex_agg = enrolled.sum(axis=0) if n_enrolled else np.zeros(24, DTYPE)
        elif policy == "curtail":
            served, _ = apply_local_curtailment(
                base_day + free_agg, enrolled.sum(axis=0), rating_kw
            )
            flex_agg = served
        elif policy == "shift":
            net_for_shift = base_day + free_agg
            if float(np.ptp(net_for_shift)) < 1e-9:
                # A (numerically) flat net load has no valley to exploit: any
                # redistribution would be an artifact of argsort tie-breaking
                # (always favoring the lowest array index), not a genuine
                # physical relief. Degenerate to the uncontrolled dispatch.
                flex_agg = enrolled.sum(axis=0)
            else:
                flex_agg = valley_fill_shift(
                    net_for_shift,
                    enrolled.sum(axis=1),  # per-EV daily energy (kWh)
                    rating_kw,
                    charger_kw[:n_enrolled],
                )
        else:
            raise ValueError(f"unknown policy {policy!r}")
        total = base_day + free_agg + flex_agg
        peaks.append(float(total[start:end].max()))
    return float(
        np.percentile(np.array(peaks, dtype=DTYPE) / float(rating_kw) * 100.0, 95)
    )
