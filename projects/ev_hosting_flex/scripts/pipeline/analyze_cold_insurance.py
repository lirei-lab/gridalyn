"""Cold-tail insurance: hosting capacity as a distribution, flexibility as insurance.

Part 1 (methodological): under winter-severity uncertainty the firm hosting count
is a DISTRIBUTION, not a number, so a point estimate leaves the feeder short in a
measurable fraction of years. Part 2 (economic): to host a target adoption, compare
REINFORCING (upgrade the transformer so firm >= A in >=95 % of years, paid every
year) against FLEXIBILITY INSURANCE (availability every year + expected activation
+ the value of the charging it denies) -- reporting where flexibility stops being
cheaper AND where it stops being viable at all.

Two honesty notes baked into the code: (a) coverage is an ENERGY-service test, not
a congestion one -- with full enrollment the backstop always holds the transformer,
so what can fail is how much charging it had to deny; (b) the denied energy is
priced at C_RETAIL_KWH so the comparison is like-for-like, because reinforcement
delivers 100 % of the EV energy and flexibility does not.

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
    cold_capability_curve,
    day_mean_temps,
    ev_fleet_annual,
    feeder_rating,
    firm_annual,
    load_annual_tmy,
    simulate_curtailment,
    tmy_hour_of_day,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    ANNUAL_RES_MINUTES,
    C_A_CURTAIL,
    C_AVAIL_EV_YR,
    C_RETAIL_KWH,
    CAPEX_UPGRADE,
    CREDIBILITY_EV_SALT,
    CREDIBILITY_K,
    CREDIBILITY_WEATHER_SALT,
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
    rating_series: np.ndarray | None = None,
    capability_curve: np.ndarray | None = None,
) -> dict[str, Any]:
    """Insurance quantities for ONE realization (one weather year).

    Returns the firm count at the present rating, the firm count at each candidate
    reinforcement rung (computed once here and reused for every adoption), and per
    adoption: whether the year falls short, whether flexibility covers it, and the
    curtailment energy the cover would cost.

    A year is COVERED when the curtailed EV-energy fraction stays within
    ``NONWIRES_CURTAIL_TOLERANCE``. Note precisely what this does and does NOT
    mean: with FULL enrollment the backstop can always hold the transformer under
    its rating (there is no un-enrolled EV draw left to spill), so the congestion
    side is satisfied *by construction* and is not a discriminating test. What can
    fail is the ENERGY side — how much charging the backstop had to deny. Coverage
    is therefore an **energy-service** criterion, not a congestion one.

    ``rung_ratings[0]`` is the present rating, so ``firm_by_rung[0]`` IS the
    present-rating firm count and is reused rather than recomputed.

    Args:
        base: Feeder base load (kW).
        pool: Per-EV demand pool (kW), prefix-swept.
        tday: Per-day mean temperatures (365,).
        rating: Feeder usable rating (kW) at the present transformer size.
        res: Step width in minutes.
        hod0: LOCAL hour-of-day phase anchor.
        adoption_grid: Target adoption levels (EV counts) to evaluate.
        rung_ratings: Usable rating (kW) of each candidate ladder rung at
            its nameplate; ``rung_ratings[0]`` is the present rating.
        rating_series: Optional per-step usable rating (kW) overriding the
            scalar ``rating`` in the curtailment simulation
            (RATING_CONVENTION); ``None`` keeps the scalar behaviour.
        capability_curve: Optional per-step multiplier on nameplate kW
            (:func:`cold_capability_curve`), applied to EVERY entry of
            ``rung_ratings`` so each candidate transformer size is judged
            under the same temperature-dependent capability as the present
            unit rather than its static 30 °C nameplate. ``None`` keeps
            every rung at its static nameplate.
    """
    firm_by_rung = [
        int(
            firm_annual(
                base,
                pool,
                float(rr),
                tday,
                hod0=hod0,
                res_minutes=res,
                rating_series=(
                    None if capability_curve is None else float(rr) * capability_curve
                ),
            )["firm_ev_count"]
        )
        for rr in rung_ratings
    ]
    firm = int(firm_by_rung[0])
    shortfall: list[bool] = []
    covered: list[bool] = []
    curtailed_kwh: list[float] = []
    curtailed_frac: list[float] = []
    for a in adoption_grid:
        n = min(int(a), int(pool.shape[0]))
        out = simulate_curtailment(
            base,
            pool[:n],
            np.ones(n, dtype=bool),
            float(rating),
            res_minutes=res,
            rating_series=rating_series,
        )
        ck = float(np.sum(out["curtailed_kwh_by_ev"]))
        total_ev_kwh = float(np.sum(pool[:n])) * (res / 60.0)
        frac = ck / total_ev_kwh if total_ev_kwh > 0.0 else 0.0
        shortfall.append(bool(firm < int(a)))
        covered.append(bool(frac <= float(NONWIRES_CURTAIL_TOLERANCE)))
        curtailed_kwh.append(ck)
        curtailed_frac.append(frac)
    return {
        "firm": firm,
        "firm_by_rung": firm_by_rung,
        "shortfall": shortfall,
        "covered": covered,
        "curtailed_kwh": curtailed_kwh,
        "curtailed_frac": curtailed_frac,
    }


def _reinforcement_for_adoption(
    firm_rung: np.ndarray,
    rung_kvas: list[float],
    adoption: int,
    target: float,
    crf: float,
) -> tuple[float | None, float | None]:
    """Smallest ladder rung reaching ``firm >= adoption`` in >= ``target`` of the
    realizations, and its annualized cost.

    Returns ``(kva, cost)`` where ``cost`` is ``0.0`` when the PRESENT unit already
    suffices (nothing to buy) and ``(None, None)`` when no rung on the ladder
    reaches the target.
    """
    for j, kva in enumerate(rung_kvas):
        if float((firm_rung[:, j] >= adoption).mean()) >= target:
            if float(kva) <= float(TRANSFORMER_KVA):
                return float(kva), 0.0
            return (
                float(kva),
                round(float(TRAFO_CAPEX_PER_KVA) * float(kva) * crf, ROUND_DECIMALS),
            )
    return None, None


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
    year, PLUS the expected activation cost, PLUS the value of the charging the
    backstop denies.

    That last term is what makes the comparison like-for-like. Reinforcement
    delivers 100 % of the EV energy; flexibility buys its cheaper headline by
    denying some charging. Pricing the denied energy at ``C_RETAIL_KWH`` puts both
    strategies on the same service basis, so the cost comparison is not an artifact
    of one strategy quietly delivering less. ``unserved_value`` is reported
    separately so the size of that concession stays visible.

    ``activation_frequency`` is a PLANNING statistic — the fraction of years whose
    firm count falls below the target adoption. It is deliberately NOT the driver
    of the activation cost, which is the expected curtailment over ALL years
    (real-time overload does not coincide exactly with the P95 planning rule).
    """
    shortfall = np.array([r["shortfall"] for r in rows], dtype=bool)  # (K, A)
    covered = np.array([r["covered"] for r in rows], dtype=bool)  # (K, A)
    ck = np.array([r["curtailed_kwh"] for r in rows], dtype=DTYPE)  # (K, A)
    cfrac = np.array([r["curtailed_frac"] for r in rows], dtype=DTYPE)  # (K, A)
    firm_rung = np.array([r["firm_by_rung"] for r in rows], dtype=DTYPE)  # (K, R)

    activation, coverage, residual, viable = [], [], [], []
    cost_flex, cost_reinforce, kva_required = [], [], []
    unserved_value, mean_curtailed_frac = [], []
    for i, a in enumerate(adoption_grid):
        act = float(shortfall[:, i].mean())
        cov = float(covered[:, i].mean())
        activation.append(round(act, ROUND_DECIMALS))
        coverage.append(round(cov, ROUND_DECIMALS))
        residual.append(round(1.0 - cov, ROUND_DECIMALS))
        viable.append(bool(cov >= float(target)))
        mean_ck = float(ck[:, i].mean())
        unserved = float(C_RETAIL_KWH) * mean_ck
        unserved_value.append(round(unserved, ROUND_DECIMALS))
        mean_curtailed_frac.append(round(float(cfrac[:, i].mean()), ROUND_DECIMALS))
        cost_flex.append(
            round(
                float(C_AVAIL_EV_YR) * int(a) + float(C_A_CURTAIL) * mean_ck + unserved,
                ROUND_DECIMALS,
            )
        )
        chosen_kva, cost_r = _reinforcement_for_adoption(
            firm_rung, rung_kvas, int(a), float(target), float(crf)
        )
        kva_required.append(chosen_kva)
        cost_reinforce.append(cost_r)

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

    # Sensitivity: the crossover is an INTEGER and the project carries a second,
    # flatter reinforcement anchor (pilar-1's CAPEX_UPGRADE, a per-upgrade lump
    # rather than TRAFO_CAPEX_PER_KVA x the new rung's full kVA). Recompute the
    # crossover under it so the headline's fragility is visible rather than implied.
    alt_annual = float(CAPEX_UPGRADE) * float(crf)
    crossover_flat_capex = None
    for i, a in enumerate(adoption_grid):
        cr = cost_reinforce[i]
        if cr is not None and cr > 0.0 and viable[i] and cost_flex[i] >= alt_annual:
            crossover_flat_capex = int(a)
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
        "unserved_value_by_adoption": unserved_value,
        "mean_curtailed_frac_by_adoption": mean_curtailed_frac,
        "crossover_adoption": crossover,
        "crossover_adoption_flat_capex": crossover_flat_capex,
        "reinforce_annual_flat_capex": round(alt_annual, ROUND_DECIMALS),
        "flex_viability_limit_adoption": viability_limit,
    }


def derive_cold_insurance(cache_dir: Path) -> dict[str, Any]:
    """Run the K-realization MC (credibility seeds) and build both study parts."""
    n_homes = feeder_home_count(cache_dir)
    temp = load_annual_tmy()
    hod0 = int(tmy_hour_of_day(temp))
    tday = day_mean_temps(temp)
    res = int(ANNUAL_RES_MINUTES)
    # Each hour is judged against the capability its OWN ambient allows
    # (RATING_CONVENTION). `cap` is the nameplate scalar kept for reporting;
    # `series` is what a load is actually compared against at the present rung.
    cap, series = feeder_rating(temp)
    # The rung ladder is ALSO a set of nameplates: the same capability
    # multiplier applies regardless of transformer size (it is a fraction of
    # nameplate, not an absolute kW), so scale every rung by the identical
    # curve rather than only the present unit.
    capability_curve = (
        None if series is None else cold_capability_curve(temp, res_minutes=res)
    )
    k = int(CREDIBILITY_K)
    offsets = winter_offsets(k, float(WEATHER_SIGMA_C), int(CREDIBILITY_WEATHER_SALT))
    grid = [int(a) for a in INSURANCE_ADOPTION_GRID]
    # Reinforcement candidates: the present rung and everything above it
    rung_kvas = [
        float(x) for x in TRANSFORMER_KVA_LADDER if x >= float(TRANSFORMER_KVA)
    ]
    rung_ratings = [kva * float(POWER_FACTOR) for kva in rung_kvas]

    if max(grid) > int(POOL_MAX_ANNUAL):
        raise ValueError(
            f"INSURANCE_ADOPTION_GRID tops out at {max(grid)} but the EV pool holds "
            f"only {POOL_MAX_ANNUAL}; the physics would silently clamp while the "
            "availability premium kept rising. Remediation: raise POOL_MAX_ANNUAL "
            "or lower the grid."
        )

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
                base_r,
                pool_r,
                tday_r,
                cap,
                res,
                hod0,
                grid,
                rung_ratings,
                rating_series=series,
                capability_curve=capability_curve,
            )
        )

    crf = capital_recovery_factor(float(DISCOUNT_RATE), int(LIFE_YEARS))
    agg = aggregate_insurance(rows, grid, rung_kvas, INSURANCE_RELIABILITY_TARGET, crf)

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
    if ref not in grid:
        raise ValueError(
            f"INSURANCE_REF_ADOPTION={ref} is not in INSURANCE_ADOPTION_GRID={grid}; "
            "every *_at_ref metric would be mislabelled. Remediation: put the "
            "reference adoption on the grid."
        )
    ref_i = grid.index(ref)
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
