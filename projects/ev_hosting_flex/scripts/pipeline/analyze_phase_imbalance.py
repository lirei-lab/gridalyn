"""Phase-imbalance DIAGNOSTIC (3-phase MV, diagnosis before solutions).

The HQ LV is single-phase 240 V split-phase; the phase imbalance is at 25 kV MV,
where single-phase pole transformers are spread across the three phases. This
stage models that with runpp_3ph: each pole transformer is a single-phase load on
its MV bus (round-robin phase), carrying its cold coincident peak (base + MC EV
adoption). Stochastic EV adoption that clusters on one phase undervolts it —
invisible in the balanced model. No flexibility. Out of scope: the single-phase
LV, full-net LV 3-phase.
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
    to_three_phase_mv,
    vuf,
)
from projects.ev_hosting_flex.scripts.pipeline.validate_powerflow import (  # noqa: E402
    size_network_to_load,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    COLD_DAY_TMEAN_C,
    DTYPE,
    PHASE_EV_GRID,
    PHASE_MC_DRAWS,
    PHASE_R0_MULT,
    PHASE_RISK_THRESHOLD,
    PHASE_X0_MULT,
    POWER_FACTOR,
    PROJECT_OUTPUTS_DIR,
    ROUND_DECIMALS,
    SEED,
    VOLTAGE_LIMITS_PU,
)


def _solve_phase_min_v(
    mv: Any,
    pole_to_mv: dict[int, int],
    load_kw_by_trafo: dict[int, float],
    *,
    balanced: bool,
) -> dict[str, float]:
    """Place each transformer's load and solve runpp_3ph; return min per-phase
    voltage + VUF over the MV buses. ``balanced`` splits each load equally across
    the phases; otherwise it is single-phase, round-robin by transformer index."""
    import pandapower as pp

    mv.asymmetric_load = mv.asymmetric_load.iloc[0:0]
    pf = float(POWER_FACTOR)
    qf = float(np.tan(np.arccos(pf)))
    for i, t in enumerate(sorted(pole_to_mv)):
        kw = float(load_kw_by_trafo.get(t, 0.0))
        if balanced:
            p = [kw / 3.0 / 1000.0] * 3
        else:
            p = [0.0, 0.0, 0.0]
            p[i % 3] = kw / 1000.0
        pp.create_asymmetric_load(
            mv, bus=int(pole_to_mv[t]), p_a_mw=p[0], p_b_mw=p[1], p_c_mw=p[2],
            q_a_mvar=p[0] * qf, q_b_mvar=p[1] * qf, q_c_mvar=p[2] * qf,
        )
    pp.runpp_3ph(mv)
    mv_buses = list(pole_to_mv.values())
    v = mv.res_bus_3ph.loc[mv_buses, ["vm_a_pu", "vm_b_pu", "vm_c_pu"]]
    worst = v.min(axis=1).idxmin()
    row = v.loc[worst]
    return {
        "min_vm_pu": float(v.min().min()),
        "vuf": float(vuf(row["vm_a_pu"], row["vm_b_pu"], row["vm_c_pu"])),
    }
