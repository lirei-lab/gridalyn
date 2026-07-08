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
