"""Probabilistic congestion-risk DIAGNOSTIC (diagnosis before solutions).

Monte-Carlos both stochastic generators — the SDK building base
(``annual_base_realization``, per distinct transformer size, cached) and the EV
fleet (``ev_fleet_annual``) — crosses them on cold days, and takes the 15-min
coincident daily-max peak, to estimate the PROBABILITY and PEAK-SEVERITY of
congestion across a realistic load-growth surface (G × EV/home). Peaks, not
averages; cold-conditioned. No flexibility. Pure-kW; transformers of equal
home-count are statistically identical, so stats are computed per distinct size
and mapped to the 540. Out of scope: flexibility, AC voltage, phase imbalance.
"""

from __future__ import annotations

import argparse
import json
import math
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
    annual_base_realization,
    day_mean_temps,
    ev_fleet_annual,
    load_annual_tmy,
    tmy_hour_of_day,
)
from projects.ev_hosting_flex.scripts._powerflow import (  # noqa: E402
    _cold_day_peaks,
    congestion_stats,
)
from projects.ev_hosting_flex.scripts.pipeline.validate_powerflow import (  # noqa: E402
    size_network_to_load,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    ANNUAL_RES_MINUTES,
    COLD_DAY_TMEAN_C,
    CONGESTION_AT_RISK_FRACTION,
    CONGESTION_EV_PER_HOME_GRID,
    CONGESTION_G_GRID,
    CONGESTION_K_BASE,
    CONGESTION_K_EV,
    CONGESTION_RISK_THRESHOLD,
    DTYPE,
    POWER_FACTOR,
    PROJECT_OUTPUTS_DIR,
    ROUND_DECIMALS,
    SEED,
)

_STEPS_PER_DAY = 24 * (60 // int(ANNUAL_RES_MINUTES))


def _ensure_base_mc_cache(
    data_dir: Path, temp: Any, sizes: list[int], k_base: int
) -> dict[int, np.ndarray]:
    """K base realizations per distinct home-count, cached in an npz.

    Returns ``{home_count: (k_base, n_steps) kW}``. Deterministic (seeds derived
    from SEED); regenerates only if the cache is absent.
    """
    path = data_dir / "base_mc_by_size.npz"
    if path.is_file():
        z = np.load(path)
        return {int(k): z[k].astype(DTYPE) for k in z.files}
    out: dict[int, np.ndarray] = {}
    for h in sorted(sizes):
        out[h] = np.stack(
            [
                annual_base_realization(temp, int(h), SEED + 100003 + int(h) * 211 + k)
                for k in range(int(k_base))
            ]
        ).astype(DTYPE)
    np.savez(path, **{str(h): out[h] for h in out})
    return out


def _ev_pools(
    n_max: int, tday: np.ndarray, hod0: int, k_ev: int
) -> list[np.ndarray]:
    """K EV-fleet draws of ``n_max`` EVs each; per-scenario counts use prefixes."""
    return [
        ev_fleet_annual(
            np.random.default_rng(SEED + 500003 + k), int(n_max), tday, int(hod0)
        ).astype(DTYPE)
        for k in range(int(k_ev))
    ]


def _size_congestion(
    base_mc: np.ndarray,
    ev_pools: list[np.ndarray],
    cold_mask: np.ndarray,
    steps_per_day: int,
    *,
    homes: int,
    rating_kw: float,
    g: float,
    ev_per_home: float,
) -> dict[str, float]:
    """Congestion stats for one (size, G, ev/home) — base×EV×cold-day peaks."""
    n_evs = int(round(float(ev_per_home) * int(homes)))
    peaks: list[np.ndarray] = []
    for kb in range(base_mc.shape[0]):
        base_g = base_mc[kb] * float(g)
        if n_evs <= 0:
            peaks.append(_cold_day_peaks(base_g, cold_mask, steps_per_day))
            continue
        for pool in ev_pools:
            total = base_g + pool[:n_evs].sum(axis=0)
            peaks.append(_cold_day_peaks(total, cold_mask, steps_per_day))
    return congestion_stats(np.concatenate(peaks), rating_kw)
