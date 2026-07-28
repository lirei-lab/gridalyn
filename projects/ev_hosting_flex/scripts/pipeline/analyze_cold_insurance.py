"""Cold-tail insurance: hosting capacity as a distribution, flexibility as insurance.

Part 1 (methodological): under winter-severity uncertainty the firm hosting count
is a DISTRIBUTION, not a number, so a point estimate leaves the feeder short in a
measurable fraction of years. Part 2 (economic): to host a target adoption, compare
REINFORCING (upgrade the transformer so firm >= A in >=95 % of years, paid every
year) against FLEXIBILITY INSURANCE (availability every year + activation only in
the cold years that fall short) -- at the SAME reliability target, reporting where
flexibility stops being cheaper AND where it stops being viable at all.

Reuses the credibility seeds and winter anomalies verbatim, so the two studies
share one firm distribution (guarded by a consistency test). No SDK edit.
"""

from __future__ import annotations

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

from projects.ev_hosting_flex.scripts._annual import (  # noqa: E402
    firm_annual,
    simulate_curtailment,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    C_A_CURTAIL,
    C_AVAIL_EV_YR,
    DTYPE,
    NONWIRES_CURTAIL_TOLERANCE,
    POWER_FACTOR,
    ROUND_DECIMALS,
    TRAFO_CAPEX_PER_KVA,
    TRANSFORMER_KVA,
)

_RATING_KW = float(TRANSFORMER_KVA) * float(POWER_FACTOR)


def realization_insurance(
    base: np.ndarray,
    pool: np.ndarray,
    tday: np.ndarray,
    rating: float,
    res: int,
    hod0: int,
    adoption_grid: list[int],
    rung_ratings: list[float],
) -> dict[str, Any]:
    """Insurance quantities for ONE realization (one weather year).

    Returns the firm count at the present rating, the firm count at each candidate
    reinforcement rung (computed once here and reused for every adoption), and per
    adoption: whether the year falls short, whether flexibility covers it, and the
    curtailment energy the cover would cost.

    A year is COVERED when curtailment holds residual congestion at the base floor
    AND the curtailed EV-energy fraction stays within ``NONWIRES_CURTAIL_TOLERANCE``.
    Years with no shortfall are covered trivially.
    """
    firm = int(
        firm_annual(base, pool, rating, tday, hod0=hod0, res_minutes=res)[
            "firm_ev_count"
        ]
    )
    firm_by_rung = [
        int(
            firm_annual(base, pool, float(rr), tday, hod0=hod0, res_minutes=res)[
                "firm_ev_count"
            ]
        )
        for rr in rung_ratings
    ]
    shortfall: list[bool] = []
    covered: list[bool] = []
    curtailed_kwh: list[float] = []
    for a in adoption_grid:
        n = min(int(a), int(pool.shape[0]))
        out = simulate_curtailment(
            base, pool[:n], np.ones(n, dtype=bool), float(rating), res_minutes=res
        )
        ck = float(np.sum(out["curtailed_kwh_by_ev"]))
        total_ev_kwh = float(np.sum(pool[:n])) * (res / 60.0)
        frac = ck / total_ev_kwh if total_ev_kwh > 0.0 else 0.0
        ok = bool(
            float(out["residual_hours"]) <= float(out["base_floor_hours"]) + 1e-9
            and frac <= float(NONWIRES_CURTAIL_TOLERANCE)
        )
        shortfall.append(bool(firm < int(a)))
        covered.append(ok)
        curtailed_kwh.append(ck)
    return {
        "firm": firm,
        "firm_by_rung": firm_by_rung,
        "shortfall": shortfall,
        "covered": covered,
        "curtailed_kwh": curtailed_kwh,
    }


def aggregate_insurance(
    rows: list[dict[str, Any]],
    adoption_grid: list[int],
    rung_kvas: list[float],
    target: float,
    crf: float,
) -> dict[str, Any]:
    """Turn the per-realization rows into the planning risk curve and the two
    strategy costs, per adoption level.

    Strategy R (reinforce): the smallest ladder rung whose rating reaches
    ``firm >= A`` in at least ``target`` of realizations, paid every year. If the
    PRESENT transformer already reaches it, no reinforcement is needed (cost 0.0);
    if no rung reaches it, the entry is ``None`` (off the ladder).

    Strategy F (flexibility insurance): availability for A contracted EVs every
    year, plus activation energy only in the years that fall short.
    """
    shortfall = np.array([r["shortfall"] for r in rows], dtype=bool)      # (K, A)
    covered = np.array([r["covered"] for r in rows], dtype=bool)          # (K, A)
    ck = np.array([r["curtailed_kwh"] for r in rows], dtype=DTYPE)        # (K, A)
    firm_rung = np.array([r["firm_by_rung"] for r in rows], dtype=DTYPE)  # (K, R)

    activation, coverage, residual, viable = [], [], [], []
    cost_flex, cost_reinforce, kva_required = [], [], []
    for i, a in enumerate(adoption_grid):
        act = float(shortfall[:, i].mean())
        cov = float(covered[:, i].mean())
        activation.append(round(act, ROUND_DECIMALS))
        coverage.append(round(cov, ROUND_DECIMALS))
        residual.append(round(1.0 - cov, ROUND_DECIMALS))
        viable.append(bool(cov >= float(target)))
        cost_flex.append(
            round(
                float(C_AVAIL_EV_YR) * int(a)
                + float(C_A_CURTAIL) * float(ck[:, i].mean()),
                ROUND_DECIMALS,
            )
        )
        # Strategy R: smallest rung reaching the reliability target at this adoption
        chosen_kva: float | None = None
        for j, kva in enumerate(rung_kvas):
            if float((firm_rung[:, j] >= int(a)).mean()) >= float(target):
                chosen_kva = float(kva)
                break
        kva_required.append(chosen_kva)
        if chosen_kva is None:
            cost_reinforce.append(None)                     # off the ladder
        elif chosen_kva <= float(TRANSFORMER_KVA):
            cost_reinforce.append(0.0)                      # present unit suffices
        else:
            cost_reinforce.append(
                round(
                    float(TRAFO_CAPEX_PER_KVA) * chosen_kva * float(crf),
                    ROUND_DECIMALS,
                )
            )

    # The two limits of insurance
    crossover = None
    for i, a in enumerate(adoption_grid):
        cr = cost_reinforce[i]
        if cr is not None and cr > 0.0 and viable[i] and cost_flex[i] >= cr:
            crossover = int(a)
            break
    viability_limit = None
    for i, a in enumerate(adoption_grid):
        if not viable[i]:
            viability_limit = int(a)
            break

    return {
        "adoption_grid": [int(a) for a in adoption_grid],
        "activation_frequency_by_adoption": activation,
        "coverage_by_adoption": coverage,
        "residual_risk_by_adoption": residual,
        "flex_viable_by_adoption": viable,
        "expected_cost_flex_by_adoption": cost_flex,
        "expected_cost_reinforce_by_adoption": cost_reinforce,
        "kva_required_by_adoption": kva_required,
        "crossover_adoption": crossover,
        "flex_viability_limit_adoption": viability_limit,
    }
