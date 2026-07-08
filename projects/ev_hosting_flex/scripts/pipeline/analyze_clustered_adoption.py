"""Study 3B: clustered EV adoption -> local hotspots + flexibility recovery.

At a FIXED total fleet, non-uniform ("clustered") adoption saturates the worst
last-mile transformer far earlier than the uniform metric suggests. This stage:

* PART 1 — characterization: (eje A) worst-transformer loading + count over
  limit vs the Gini of the adoption vector at a fixed mean rate; (eje B) the
  mean penetration at which the worst transformer first crosses 100%, clustered
  vs uniform (the headline gap Delta-mu).
* PART 2 — recovery: per-transformer local curtailment (static-rating cap, no
  time-shift) re-solved in AC; the hosting recovered, the curtailed energy, the
  burden concentration (Gini/Jain) on the EV-heavy clusters, and the dispersion
  floor beyond which local flex no longer recovers the uniform limit.

Reuses size_network_to_load (identical HQ-realistic model) and the fixed EV
pool. GUARD-02: no module-scope pandapower. Out of scope: phase imbalance
(needs runpp_3ph) — the balanced model carries the transformer-overload story.
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
    load_annual_tmy,
    tmy_hour_of_day,
)
from projects.ev_hosting_flex.scripts._powerflow import (  # noqa: E402
    apply_local_curtailment,
    draw_clustered_adoption,
    gini,
)
from projects.ev_hosting_flex.scripts.pipeline.analyze_network_characterization import (  # noqa: E402
    _interp_crossing,
)
from projects.ev_hosting_flex.scripts.pipeline.validate_powerflow import (  # noqa: E402
    size_network_to_load,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    CLUSTER_DISPERSION_GRID,
    CLUSTER_MC_DRAWS,
    CLUSTER_MEAN_RATE,
    CLUSTER_MU_GRID,
    DTYPE,
    POWER_FACTOR,
    PROJECT_OUTPUTS_DIR,
    ROUND_DECIMALS,
    SEED,
    SLACK_VM_PU,
)


def _solve_worst_trafo(
    net: Any,
    per_trafo_base: dict[int, np.ndarray],
    per_trafo_homes: dict[int, int],
    load_bus_to_trafo: dict[int, int],
    ev_perhome_day: np.ndarray,
    adoption: np.ndarray,
    lv_trafos: np.ndarray,
    curtail: bool,
) -> dict[str, Any]:
    """Solve one design-day (24 h) full-net PF for a given adoption vector.

    Args:
        net: sized pandapower net (mutated per hour).
        per_trafo_base: trafo_idx -> (24,) kW aggregate base at the trafo.
        per_trafo_homes: trafo_idx -> homes served.
        load_bus_to_trafo: load bus -> owning LV trafo idx.
        ev_perhome_day: (24,) per-home design-day EV profile (kW), local-ordered.
        adoption: (T,) EV/home per LV transformer (aligned to lv_trafos order).
        lv_trafos: (T,) LV transformer indices.
        curtail: if True, apply per-trafo local curtailment (static-rating cap).

    Returns:
        Dict with worst_loading (float %), n_over_static (int),
        curtailed_kwh (float, total shed), curtailed_by_trafo (T,) kWh.
    """
    import pandapower as pp

    pf = float(POWER_FACTOR)
    q_factor = float(np.tan(np.arccos(pf)))
    net.ext_grid["vm_pu"] = float(SLACK_VM_PU)

    adopt_by_trafo = {int(t): float(adoption[i]) for i, t in enumerate(lv_trafos)}
    # served EV kW per trafo per hour (after optional curtailment)
    served_ev: dict[int, np.ndarray] = {}
    curtailed_by_trafo = np.zeros(len(lv_trafos), dtype=DTYPE)
    for i, t in enumerate(lv_trafos):
        t = int(t)
        homes = per_trafo_homes[t]
        ev_kw = adopt_by_trafo[t] * homes * ev_perhome_day
        if curtail:
            sn = float(net.trafo.at[t, "sn_mva"])
            rating_kw = sn * 1000.0 * pf
            served, cur = apply_local_curtailment(per_trafo_base[t], ev_kw, rating_kw)
            served_ev[t] = served
            curtailed_by_trafo[i] = cur
        else:
            served_ev[t] = ev_kw

    load_bus = net.load["bus"].to_numpy()
    # Split each transformer's aggregate evenly across the load buses that
    # actually belong to it (NOT its home count — the two can differ, and only
    # the total throughput at the transformer, which we measure, must be exact).
    n_loadbuses: dict[int, int] = {}
    for b in load_bus:
        t = load_bus_to_trafo[int(b)]
        n_loadbuses[t] = n_loadbuses.get(t, 0) + 1
    worst = 0.0
    n_over = 0
    over_seen = np.zeros(len(lv_trafos), dtype=bool)
    for hour in range(24):
        p_kw = np.empty(len(load_bus), dtype=DTYPE)
        for k, b in enumerate(load_bus):
            t = load_bus_to_trafo[int(b)]
            nb = n_loadbuses[t]
            # split the trafo aggregate evenly across its OWN load buses
            base_h = per_trafo_base[t][hour] / nb
            ev_h = served_ev[t][hour] / nb
            p_kw[k] = base_h + ev_h
        net.load["p_mw"] = p_kw / 1000.0
        net.load["q_mvar"] = net.load["p_mw"] * q_factor
        pp.runpp(net, numba=True)
        load_pct = net.res_trafo["loading_percent"][lv_trafos].to_numpy(dtype=DTYPE)
        worst = max(worst, float(load_pct.max()))
        over_seen |= load_pct >= 100.0
    n_over = int(over_seen.sum())
    return {
        "worst_loading": worst,
        "n_over_static": n_over,
        "curtailed_kwh": float(curtailed_by_trafo.sum()),
        "curtailed_by_trafo": curtailed_by_trafo,
    }
