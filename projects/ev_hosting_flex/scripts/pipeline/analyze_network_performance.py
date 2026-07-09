"""Network performance state + load-growth hypothesis.

Characterizes the network's performance state across a load-growth sweep (G):
the network is SIZED at G=1 and EVALUATED under base × G. Per-transformer
utilization / exceedance / headroom / growth-margin over the 540 LV
transformers, the flexible-vs-inflexible peak share (the ceiling on the value
of EV flexibility), and the feeder flexibility window (uncontrolled vs optimal
shift hosting), revealing the loadedness BAND where flexibility is the right
tool. Pure-kW (no pandapower); deterministic (no RNG). Out of scope: the
governed firm/flex chain, AC, phase imbalance.
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
    climate_bin_days,
    load_annual_tmy,
    tmy_hour_of_day,
)
from projects.ev_hosting_flex.scripts._powerflow import (  # noqa: E402
    annual_performance_metrics,
    flexible_share,
)
from projects.ev_hosting_flex.scripts.pipeline.analyze_flexibility_incentive import (  # noqa: E402
    _policy_ceiling_ev_per_home,
)
from projects.ev_hosting_flex.scripts.pipeline.validate_powerflow import (  # noqa: E402
    size_network_to_load,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    CLIMATE_BIN_EDGES,
    DTYPE,
    LOAD_GROWTH_GRID,
    PERFORMANCE_REF_EV_PER_HOME,
    POOL_TILES,
    POWER_FACTOR,
    PROJECT_OUTPUTS_DIR,
    ROUND_DECIMALS,
    TRANSFORMER_KVA,
)


def _build_panel(
    per_home_hourly: np.ndarray,
    homes_by_trafo: dict[int, int],
    rating_by_trafo: dict[int, float],
    growth_grid: tuple[float, ...],
) -> dict[str, Any]:
    """Per-transformer performance metrics across the load-growth sweep.

    Args:
        per_home_hourly: ``(H,)`` per-home hourly base profile (kW/home).
        homes_by_trafo: trafo_idx -> home count.
        rating_by_trafo: trafo_idx -> usable kW rating (sized at G=1).
        growth_grid: load-growth factors G.

    Returns:
        Dict with per-G aggregates: ``n_over_100_by_g``, ``n_over_90_by_g``,
        ``median_peak_util_by_g``, ``p95_peak_util_by_g``, ``hours_over_100_p95``
        (at the highest G), and ``growth_margin_p50`` (at G=1).
    """
    per_home = np.asarray(per_home_hourly, dtype=DTYPE)
    trafos = sorted(homes_by_trafo)
    base_by_trafo = {t: per_home * homes_by_trafo[t] for t in trafos}

    n_over_100, n_over_90, median_util, p95_util = [], [], [], []
    growth_margin_g1: list[float] = []
    hours_over_100_top: list[int] = []
    for gi, g in enumerate(growth_grid):
        utils, over100, over90 = [], 0, 0
        for t in trafos:
            m = annual_performance_metrics(base_by_trafo[t] * g, rating_by_trafo[t])
            utils.append(m["peak_utilization_pct"])
            over100 += int(m["peak_utilization_pct"] > 100.0)
            over90 += int(m["peak_utilization_pct"] > 90.0)
            if gi == 0:
                gm = m["growth_margin_pct"]
                growth_margin_g1.append(gm if np.isfinite(gm) else 1e9)
            if g == growth_grid[-1]:
                hours_over_100_top.append(m["hours_over_100"])
        n_over_100.append(int(over100))
        n_over_90.append(int(over90))
        median_util.append(round(float(np.median(utils)), ROUND_DECIMALS))
        p95_util.append(round(float(np.percentile(utils, 95)), ROUND_DECIMALS))

    return {
        "growth_grid": [round(float(g), 6) for g in growth_grid],
        "n_trafos": len(trafos),
        "n_over_100_by_g": n_over_100,
        "n_over_90_by_g": n_over_90,
        "median_peak_util_by_g": median_util,
        "p95_peak_util_by_g": p95_util,
        "growth_margin_p50": round(float(np.median(growth_margin_g1)), ROUND_DECIMALS),
        "hours_over_100_p95": int(np.percentile(hours_over_100_top, 95)),
    }
