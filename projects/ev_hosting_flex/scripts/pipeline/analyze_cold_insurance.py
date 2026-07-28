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

from projects.ev_hosting_flex.scripts._annual import (  # noqa: E402
    N_DAYS,
    annual_base_realization,
    day_mean_temps,
    ev_fleet_annual,
    firm_annual,
    load_annual_tmy,
    simulate_curtailment,
    tmy_hour_of_day,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    ANNUAL_RES_MINUTES,
    CREDIBILITY_EV_SALT,
    CREDIBILITY_K,
    CREDIBILITY_WEATHER_SALT,
    C_A_CURTAIL,
    C_AVAIL_EV_YR,
    DISCOUNT_RATE,
    DTYPE,
    INSURANCE_ADOPTION_GRID,
    INSURANCE_REF_ADOPTION,
    INSURANCE_RELIABILITY_TARGET,
    LIFE_YEARS,
    NONWIRES_CURTAIL_TOLERANCE,
    POOL_MAX_ANNUAL,
    POWER_FACTOR,
    PROJECT_OUTPUTS_DIR,
    ROUND_DECIMALS,
    SEED,
    TRAFO_CAPEX_PER_KVA,
    TRANSFORMER_KVA,
    TRANSFORMER_KVA_LADDER,
    WEATHER_SIGMA_C,
)
from projects.ev_hosting_flex.scripts.pipeline.analyze_credibility import (  # noqa: E402
    winter_offsets,
)
from projects.ev_hosting_flex.scripts.pipeline.compute_curtailment_economics import (  # noqa: E402
    capital_recovery_factor,
)
from projects.ev_hosting_flex.scripts.pipeline.generate_annual_mc import (  # noqa: E402
    feeder_home_count,
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


def derive_cold_insurance(cache_dir: Path) -> dict[str, Any]:
    """Run the K-realization MC (credibility seeds) and build both study parts."""
    n_homes = feeder_home_count(cache_dir)
    temp = load_annual_tmy()
    hod0 = int(tmy_hour_of_day(temp))
    tday = day_mean_temps(temp)
    res = int(ANNUAL_RES_MINUTES)
    k = int(CREDIBILITY_K)
    offsets = winter_offsets(k, float(WEATHER_SIGMA_C), int(CREDIBILITY_WEATHER_SALT))
    grid = [int(a) for a in INSURANCE_ADOPTION_GRID]
    # Reinforcement candidates: the present rung and everything above it
    rung_kvas = [
        float(x) for x in TRANSFORMER_KVA_LADDER if x >= float(TRANSFORMER_KVA)
    ]
    rung_ratings = [kva * float(POWER_FACTOR) for kva in rung_kvas]

    rows: list[dict[str, Any]] = []
    for r in range(k):
        delta = float(offsets[r])
        base_r = annual_base_realization(
            temp,
            int(n_homes),
            int(SEED) + r,
            per_day_offset_c=np.full(int(N_DAYS), delta, dtype=DTYPE),
        )
        tday_r = tday + delta
        pool_r = ev_fleet_annual(
            np.random.default_rng(int(SEED) + int(CREDIBILITY_EV_SALT) * r),
            int(POOL_MAX_ANNUAL),
            tday_r,
            hod0,
        )
        rows.append(
            realization_insurance(
                base_r, pool_r, tday_r, _RATING_KW, res, hod0, grid, rung_ratings
            )
        )

    crf = capital_recovery_factor(float(DISCOUNT_RATE), int(LIFE_YEARS))
    agg = aggregate_insurance(
        rows, grid, rung_kvas, INSURANCE_RELIABILITY_TARGET, crf
    )

    # ── Part 1: the hosting-capacity distribution ────────────────────────────
    firm = np.array([row["firm"] for row in rows], dtype=DTYPE)
    values, counts = np.unique(firm, return_counts=True)
    p05 = float(np.percentile(firm, 5))
    p50 = float(np.percentile(firm, 50))
    p95 = float(np.percentile(firm, 95))
    # The cost of a point estimate: plan at P50 (or P5) -> what fraction of years
    # is the feeder short?
    short_if_plan_p50 = round(float((firm < p50).mean()), ROUND_DECIMALS)
    short_if_plan_p05 = round(float((firm < p05).mean()), ROUND_DECIMALS)
    # Mechanism: colder year -> lower firm (evidence the spread is weather, not noise)
    delta_firm_corr = (
        round(
            float(np.corrcoef(np.asarray(offsets, dtype=DTYPE), firm)[0, 1]),
            ROUND_DECIMALS,
        )
        if float(np.std(firm)) > 0.0
        else None
    )

    ref = int(INSURANCE_REF_ADOPTION)
    ref_i = grid.index(ref) if ref in grid else len(grid) - 1
    payload = {
        "k": k,
        "weather_sigma_c": float(WEATHER_SIGMA_C),
        "reliability_target": float(INSURANCE_RELIABILITY_TARGET),
        "n_homes": int(n_homes),
        "rating_kw": round(_RATING_KW, ROUND_DECIMALS),
        "crf": round(crf, ROUND_DECIMALS),
        "rung_kvas": rung_kvas,
        # Part 1
        "firm_samples": [int(v) for v in firm],
        "firm_histogram": {str(int(v)): int(c) for v, c in zip(values, counts)},
        "firm_p05": round(p05, ROUND_DECIMALS),
        "firm_p50": round(p50, ROUND_DECIMALS),
        "firm_p95": round(p95, ROUND_DECIMALS),
        "short_years_if_plan_p50": short_if_plan_p50,
        "short_years_if_plan_p05": short_if_plan_p05,
        "delta_firm_correlation": delta_firm_corr,
        # Part 2
        **agg,
        # Reference-adoption headlines
        "reference_adoption": ref,
        "p_short_at_ref": agg["activation_frequency_by_adoption"][ref_i],
        "activation_frequency_at_ref": agg["activation_frequency_by_adoption"][ref_i],
        "coverage_at_ref": agg["coverage_by_adoption"][ref_i],
        "expected_cost_flex_at_ref": agg["expected_cost_flex_by_adoption"][ref_i],
        "expected_cost_reinforce_at_ref": (
            agg["expected_cost_reinforce_by_adoption"][ref_i]
        ),
    }
    json_dir = PROJECT_OUTPUTS_DIR / "json"
    json_dir.mkdir(parents=True, exist_ok=True)
    out_path = json_dir / "cold_insurance.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    fig_paths = _figures(payload, PROJECT_OUTPUTS_DIR / "figures")
    summary = {
        "p_short_at_ref": payload["p_short_at_ref"],
        "activation_frequency_at_ref": payload["activation_frequency_at_ref"],
        "coverage_at_ref": payload["coverage_at_ref"],
        "expected_cost_flex_at_ref": payload["expected_cost_flex_at_ref"],
        "expected_cost_reinforce_at_ref": payload["expected_cost_reinforce_at_ref"],
        "crossover_adoption": payload["crossover_adoption"],
        "flex_viability_limit_adoption": payload["flex_viability_limit_adoption"],
        "short_years_if_plan_p50": payload["short_years_if_plan_p50"],
    }
    return {"artifact_paths": [out_path, *fig_paths], "summary": summary}


def _figures(payload: dict[str, Any], figures_dir: Path) -> list[Path]:
    """Three panels: the capacity distribution + planning risk curve; the two
    strategy costs; activation frequency and coverage."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    grid = payload["adoption_grid"]
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(15.0, 4.4))

    # A: firm distribution + planning risk curve
    hist = payload["firm_histogram"]
    xs = sorted(int(v) for v in hist)
    ax1.bar(
        xs,
        [hist[str(v)] for v in xs],
        color="C0",
        alpha=0.75,
        label="firm (K years)",
    )
    ax1.axvline(
        payload["firm_p50"],
        color="k",
        ls="--",
        lw=1.2,
        label=f"P50 {payload['firm_p50']:g}",
    )
    ax1.axvline(
        payload["firm_p05"],
        color="C3",
        ls=":",
        lw=1.2,
        label=f"P5 {payload['firm_p05']:g}",
    )
    ax1.set_xlabel("firm hosting (EVs)")
    ax1.set_ylabel("years")
    ax1.set_title(
        f"A. Capacity is a distribution\nplanning at P50 is short "
        f"{100 * payload['short_years_if_plan_p50']:.0f}% of years"
    )
    ax1.legend(fontsize=7)

    # B: strategy costs vs adoption (shade where flex is not viable)
    cf = payload["expected_cost_flex_by_adoption"]
    cr = payload["expected_cost_reinforce_by_adoption"]
    ax2.plot(grid, cf, "o-", color="C2", label="flexibility insurance")
    cr_x = [a for a, c in zip(grid, cr) if c is not None]
    cr_y = [c for c in cr if c is not None]
    ax2.plot(cr_x, cr_y, "s--", color="C1", label="reinforce")
    lim = payload["flex_viability_limit_adoption"]
    if lim is not None:
        ax2.axvspan(lim, max(grid), color="0.85", alpha=0.6, label="flex not viable")
    if payload["crossover_adoption"] is not None:
        ax2.axvline(
            payload["crossover_adoption"],
            color="k",
            ls=":",
            lw=1.5,
            label=f"crossover {payload['crossover_adoption']}",
        )
    ax2.set_xlabel("target adoption (EVs)")
    ax2.set_ylabel("expected annual cost ($)")
    ax2.set_title("B. Insurance vs reinforcement\n(equal 95% reliability)")
    ax2.legend(fontsize=7)

    # C: activation frequency + coverage
    ax3.plot(
        grid,
        payload["activation_frequency_by_adoption"],
        "o-",
        color="C3",
        label="activation frequency P(firm<A)",
    )
    ax3.plot(
        grid,
        payload["coverage_by_adoption"],
        "s-",
        color="C0",
        label="coverage",
    )
    ax3.axhline(
        payload["reliability_target"],
        color="k",
        ls="--",
        lw=1,
        label=f"target {payload['reliability_target']:g}",
    )
    ax3.set_xlabel("target adoption (EVs)")
    ax3.set_ylabel("fraction of years")
    ax3.set_title("C. How often insurance is called,\nand whether it holds")
    ax3.legend(fontsize=7)

    fig.suptitle(
        "Cold-tail insurance: hosting capacity as a distribution, "
        "flexibility as insurance",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    paths = []
    for suffix in (".png", ".pdf"):
        p = figures_dir / f"cold_insurance{suffix}"
        fig.savefig(p, dpi=200, bbox_inches="tight")
        paths.append(p)
    plt.close(fig)
    return paths


def run_stage() -> dict[str, Any]:
    """Run the cold-tail insurance study and emit the platform report."""
    from gridalyn.projects.scripting import project_script

    script = project_script()
    derived = derive_cold_insurance(script.cache_dir)
    warnings = [
        "SOLUTION framing: the network is robust at the MEDIAN (validated against "
        "the real HQ 1000-home dataset), so this study prices flexibility where it "
        "actually binds -- the cold tail -- as insurance, not as a network rescue.",
        "SYNTHETIC CLIMATE AXIS: winter severity is a synthetic anomaly "
        "(uniform N(0, sigma) per-day offset on a single TMY), NOT measured weather "
        "years. K finite -> the tail probabilities carry sampling error.",
        "EQUAL-RELIABILITY COMPARISON: both strategies must cover >= the reliability "
        "target; they are compared on cost, and the adoption where flexibility stops "
        "being VIABLE at any cost is reported alongside the cost crossover.",
        "ILLUSTRATIVE COSTS (C_AVAIL_EV_YR, C_A_CURTAIL, TRAFO_CAPEX_PER_KVA): the "
        "robust results are the SHAPE of the comparison and the activation frequency, "
        "not the absolute dollars. Governed 6-home feeder; the insurance assumes "
        "enrolled flexibility is available when called (an upper bound).",
    ]
    return script.write_report(
        "cold_insurance_report",
        artifacts=[script.file_reference(p) for p in derived["artifact_paths"]],
        summary=derived["summary"],
        validation={"valid": True, "errors": [], "warnings": warnings},
    )


def main() -> None:
    """CLI entry point for the cold-tail insurance study."""
    argparse.ArgumentParser(description=__doc__).parse_args()
    report = run_stage()
    s = report.get("summary", {})
    print(
        "Cold-tail insurance + report: planning at P50 is short "
        f"{100 * float(s.get('short_years_if_plan_p50', 0.0)):.0f}% of years | "
        f"at {INSURANCE_REF_ADOPTION} EVs: P(short) {s.get('p_short_at_ref')}, "
        f"coverage {s.get('coverage_at_ref')}, flex ${s.get('expected_cost_flex_at_ref')} "
        f"vs reinforce ${s.get('expected_cost_reinforce_at_ref')} | crossover "
        f"{s.get('crossover_adoption')} EVs | flex viable until "
        f"{s.get('flex_viability_limit_adoption')}"
    )


if __name__ == "__main__":
    main()
