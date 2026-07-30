"""Fleet triage: how many of the 540 pole transformers does flexibility defer?

The study's flexibility results were measured on ONE governed feeder. This
stage scales them to the whole fleet and answers the planning question
directly: at a given EV adoption, how many transformers never bind, how many a
flexibility contract defers, and how many need steel regardless.

Two corrections to the per-asset result are built in.

1. The published flexible count was POOL-LIMITED. `apply_curtailment_contracts`
   accepts a count when ``residual_hours <= base_floor``, but under full
   enrollment the backstop can always hold the feeder -- it simply curtails
   more -- so that gate is near-vacuous and the answer equalled the pool size.
   Here the flexible count is gated on the CURTAILMENT TOLERANCE, i.e. on the
   service denied to the customer, which is what actually bounds a contract.

2. The fleet is dominated by assets whose constraint is the cold building base,
   not EVs. Those cannot be deferred by an EV contract at any relief strength,
   and the triage reports them separately rather than averaging them away.
"""

from __future__ import annotations

import argparse
import json
import math
import pickle
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from projects.ev_hosting_flex.scripts._annual import (  # noqa: E402
    ANNUAL_RES_MINUTES,
    cold_capability_curve,
    day_mean_temps,
    firm_annual,
    load_annual_tmy,
    simulate_curtailment,
    tmy_hour_of_day,
)
from projects.ev_hosting_flex.scripts._powerflow import (  # noqa: E402
    draw_clustered_adoption,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    DISCOUNT_RATE,
    LIFE_YEARS,
    POWER_FACTOR,
    PROJECT_OUTPUTS_DIR,
    ROUND_DECIMALS,
    SEED,
    TRAFO_CAPEX_PER_KVA,
    TRANSFORMER_KVA_LADDER,
    TRIAGE_ADOPTION_GRID,
    TRIAGE_BASE_DISPERSION,
    TRIAGE_BASE_FLOOR_TOLERANCE_H,
    TRIAGE_CLUSTER_DRAWS,
    TRIAGE_CURTAIL_TOLERANCE,
    TRIAGE_HOTSPOT_LIMIT_C,
    TRIAGE_RATING_CONVENTIONS,
    TRIAGE_DISPERSION_GRID,
    TRIAGE_K_BASE,
    TRIAGE_POOL_PER_HOME,
)
from projects.ev_hosting_flex.scripts.pipeline.analyze_congestion_risk import (  # noqa: E402
    _ensure_base_mc_cache,
    _ev_pools,
)
from projects.ev_hosting_flex.scripts.pipeline.validate_powerflow import (  # noqa: E402
    size_network_to_load,
)

_HOURS_PER_STEP = float(ANNUAL_RES_MINUTES) / 60.0

NEVER_BINDS = "never_binds"
FLEX_DEFERS = "flex_defers"
NEEDS_STEEL = "needs_steel"
BASE_CONSTRAINED = "base_constrained"


def curtailed_fraction(
    base: np.ndarray,
    pool: np.ndarray,
    n_evs: int,
    rating_kw: float,
    rating_series: np.ndarray | None = None,
) -> float:
    """Return the fraction of EV energy the contract must deny at ``n_evs``.

    Full enrollment, fair rotation -- the governed contract mechanism.

    Args:
        base: ``(horizon,)`` feeder base in kW.
        pool: ``(n_max, horizon)`` per-EV demand in kW.
        n_evs: EV count to evaluate (row prefix of ``pool``).
        rating_kw: Transformer usable rating in kW.

    Returns:
        Curtailed energy divided by requested energy, 0.0 when ``n_evs <= 0``.
    """
    if n_evs <= 0:
        return 0.0
    out = simulate_curtailment(
        base,
        pool[:n_evs],
        np.ones(int(n_evs), bool),
        float(rating_kw),
        res_minutes=ANNUAL_RES_MINUTES,
        rating_series=rating_series,
    )
    requested = float(pool[:n_evs].sum()) * _HOURS_PER_STEP
    if requested <= 0.0:
        return 0.0
    return float(out["curtailed_kwh_by_ev"].sum()) / requested


def flexible_count(
    base: np.ndarray,
    pool: np.ndarray,
    rating_kw: float,
    tolerance: float,
    rating_series: np.ndarray | None = None,
) -> int:
    """Return the largest EV count a contract serves within ``tolerance``.

    Bisects rather than scanning: the curtailed fraction is monotone
    non-decreasing in the EV count (more demand behind the same headroom can
    only deny more), so bisection finds the same answer in ``log2(n)`` annual
    simulations instead of ``n``.

    Args:
        base: ``(horizon,)`` feeder base in kW.
        pool: ``(n_max, horizon)`` per-EV demand in kW.
        rating_kw: Transformer usable rating in kW.
        tolerance: Max curtailed EV-energy fraction (a commercial term).

    Returns:
        The EV count, 0 if even a single EV exceeds the tolerance, and the full
        pool depth if the tolerance never binds -- in which case the answer is
        pool-limited and the caller must widen ``TRIAGE_POOL_PER_HOME``.
    """
    n_max = int(pool.shape[0])
    if n_max <= 0:
        return 0
    if curtailed_fraction(base, pool, n_max, rating_kw, rating_series) <= tolerance:
        return n_max
    lo, hi = 0, n_max  # invariant: lo is feasible, hi is not
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if curtailed_fraction(base, pool, mid, rating_kw, rating_series) <= tolerance:
            lo = mid
        else:
            hi = mid
    return lo


def _next_rung_kva(rating_kw: float) -> float | None:
    """Return the next standard transformer size above the present rating."""
    present_kva = float(rating_kw) / float(POWER_FACTOR)
    for rung in TRANSFORMER_KVA_LADDER:
        if float(rung) > present_kva + 1e-6:
            return float(rung)
    return None


def capital_recovery_factor(rate: float, years: int) -> float:
    """Return the annuity factor converting a capex to an annual charge."""
    r, n = float(rate), int(years)
    if r <= 0.0:
        return 1.0 / n
    return r * (1.0 + r) ** n / ((1.0 + r) ** n - 1.0)


def per_size_limits(
    base_mc: dict[int, np.ndarray],
    pools_by_size: dict[int, list[np.ndarray]],
    rating_by_size: dict[int, float],
    tday: np.ndarray,
    hod0: int,
    k_curve: np.ndarray | None = None,
) -> dict[int, dict[str, Any]]:
    """Return ``{homes: {firm, flexible, curtail_at_flexible}}`` per size class.

    Both counts are medians over the base realizations, so a single unlucky
    winter does not set the fleet-wide verdict.
    """
    out: dict[int, dict[str, Any]] = {}
    for homes in sorted(base_mc):
        rating = float(rating_by_size[homes])
        series = None if k_curve is None else rating * k_curve
        firm_draws: list[int] = []
        flex_draws: list[int] = []
        curt_draws: list[float] = []
        floor_draws: list[float] = []
        for k in range(base_mc[homes].shape[0]):
            base = base_mc[homes][k]
            pool = pools_by_size[homes][k % len(pools_by_size[homes])]
            # Hours the BASE ALONE is over rating: an EV contract cannot touch
            # these, so they disqualify the asset from being deferred.
            cap = rating if series is None else series
            floor_draws.append(float((base > cap).sum()) * _HOURS_PER_STEP)
            firm_draws.append(
                int(
                    firm_annual(
                        base,
                        pool,
                        rating,
                        tday,
                        hod0=int(hod0),
                        res_minutes=ANNUAL_RES_MINUTES,
                        rating_series=series,
                    )["firm_ev_count"]
                )
            )
            n_flex = flexible_count(
                base, pool, rating, float(TRIAGE_CURTAIL_TOLERANCE), series
            )
            flex_draws.append(n_flex)
            curt_draws.append(curtailed_fraction(base, pool, n_flex, rating, series))
        out[homes] = {
            "homes": homes,
            "rating_kw": round(rating, ROUND_DECIMALS),
            "firm_ev_count": int(np.median(firm_draws)),
            "flexible_ev_count": int(np.median(flex_draws)),
            "firm_ev_per_home": round(
                float(np.median(firm_draws)) / homes, ROUND_DECIMALS
            ),
            "flexible_ev_per_home": round(
                float(np.median(flex_draws)) / homes, ROUND_DECIMALS
            ),
            "curtailed_fraction_at_flexible": round(
                float(np.median(curt_draws)), ROUND_DECIMALS
            ),
            "base_floor_hours": round(float(np.median(floor_draws)), ROUND_DECIMALS),
            "base_constrained": bool(
                float(np.median(floor_draws)) > float(TRIAGE_BASE_FLOOR_TOLERANCE_H)
            ),
            "pool_limited": bool(
                int(np.median(flex_draws)) >= pools_by_size[homes][0].shape[0]
            ),
        }
    return out


def triage_fleet(
    homes_by_trafo: dict[int, int],
    limits: dict[int, dict[str, Any]],
    adoption: float,
    *,
    dispersion: float = 0.0,
    draws: int = 1,
    seed: int = 0,
) -> dict[str, Any]:
    """Classify every transformer at one adoption level and dispersion.

    EV ownership is spatially correlated, so at a FIXED fleet total the
    per-transformer adoption rate is drawn from a unit-mean lognormal
    (:func:`draw_clustered_adoption`, fleet-preserving and capped) rather than
    assumed uniform. Uniform allocation understates the worst last-mile
    transformer while reporting the same fleet size, which is why
    ``dispersion=0`` is the reference case here and not the base case.

    Args:
        homes_by_trafo: Transformer index -> connected home count.
        limits: Per-size firm/flexible counts.
        adoption: MEAN EVs per home across the fleet (invariant to dispersion).
        dispersion: Lognormal sigma of the adoption allocation; 0 = uniform.
        draws: Allocation draws averaged (the allocation is stochastic).
        seed: Base seed for the allocation draws.

    Returns:
        Counts per category (averaged over draws and rounded) plus the deferred
        and required capital.
    """
    order = sorted(homes_by_trafo)
    homes_arr = np.array([homes_by_trafo[t] for t in order], dtype=float)
    n_draws = max(1, int(draws)) if float(dispersion) > 0.0 else 1

    acc = {NEVER_BINDS: 0.0, FLEX_DEFERS: 0.0, NEEDS_STEEL: 0.0, BASE_CONSTRAINED: 0.0}
    deferred_kva = 0.0
    steel_kva = 0.0
    for d in range(n_draws):
        rng = np.random.default_rng(int(seed) + 7919 * d)
        rates = draw_clustered_adoption(
            homes_arr, float(adoption), float(dispersion), rng
        )
        for i, homes in enumerate(order):
            homes_i = int(homes_by_trafo[homes])
            lim = limits[homes_i]
            n_evs = int(round(float(rates[i]) * homes_i))
            rung = _next_rung_kva(float(lim["rating_kw"])) or 0.0
            if bool(lim["base_constrained"]):
                # Winter heating alone already overloads this asset. There is no
                # EV load to shed in those hours, so enrollment cannot defer it —
                # checked BEFORE the EV counts so such assets are never credited
                # to flexibility.
                acc[BASE_CONSTRAINED] += 1.0
                steel_kva += rung
            elif n_evs <= int(lim["firm_ev_count"]):
                acc[NEVER_BINDS] += 1.0
            elif n_evs <= int(lim["flexible_ev_count"]):
                acc[FLEX_DEFERS] += 1.0
                deferred_kva += rung
            else:
                acc[NEEDS_STEEL] += 1.0
                steel_kva += rung

    counts = {k: int(round(v / n_draws)) for k, v in acc.items()}
    at_risk = counts[FLEX_DEFERS] + counts[NEEDS_STEEL] + counts[BASE_CONSTRAINED]
    return {
        "adoption_ev_per_home": float(adoption),
        "dispersion": float(dispersion),
        "never_binds": counts[NEVER_BINDS],
        "flex_defers": counts[FLEX_DEFERS],
        "needs_steel": counts[NEEDS_STEEL],
        "base_constrained": counts[BASE_CONSTRAINED],
        "n_at_risk": at_risk,
        "deferred_fraction_of_at_risk": round(
            counts[FLEX_DEFERS] / at_risk if at_risk else 0.0, ROUND_DECIMALS
        ),
        "deferred_capex_usd": round(
            deferred_kva / n_draws * float(TRAFO_CAPEX_PER_KVA), 2
        ),
        "steel_capex_usd": round(steel_kva / n_draws * float(TRAFO_CAPEX_PER_KVA), 2),
    }


def derive_fleet_triage(cache_dir: Path, data_dir: Path) -> dict[str, Any]:
    """Compute per-size hosting limits and triage the whole transformer fleet."""
    with open(cache_dir / "pp_net_cache.pkl", "rb") as handle:
        net = pickle.load(handle)
    feeder_idx = int(
        json.loads((cache_dir / "feeder_selection.json").read_text())[
            "feeder_transformer_idx"
        ]
    )
    temp = load_annual_tmy()
    hod0 = int(tmy_hour_of_day(temp))
    tday = day_mean_temps(temp)
    design_day = int(np.argmin(tday))
    sizing = size_network_to_load(net, cache_dir, temp, design_day, feeder_idx)
    size_by_trafo = sizing["size_by_trafo"]

    pf = float(POWER_FACTOR)
    lv = net.trafo.index[net.trafo["vn_lv_kv"] < 1.0]
    homes_by_trafo = {int(t): int(size_by_trafo[int(t)]) for t in lv}
    rating_by_trafo = {
        int(t): float(net.trafo.at[int(t), "sn_mva"]) * 1000.0 * pf for t in lv
    }
    sizes = sorted(set(homes_by_trafo.values()))
    rating_by_size: dict[int, float] = {}
    for h in sizes:
        group = {rating_by_trafo[t] for t in homes_by_trafo if homes_by_trafo[t] == h}
        if len(group) != 1:
            raise ValueError(
                f"transformers with {h} homes have non-uniform ratings {group}; "
                "the per-size triage assumes one rating per size."
            )
        rating_by_size[h] = group.pop()

    base_mc = _ensure_base_mc_cache(data_dir, temp, sizes, int(TRIAGE_K_BASE))
    pools_by_size: dict[int, list[np.ndarray]] = {}
    for h in sizes:
        depth = int(math.ceil(float(TRIAGE_POOL_PER_HOME) * h))
        pools_by_size[h] = _ev_pools(depth, tday, hod0, int(TRIAGE_K_BASE))

    # Both rating conventions in one run. They are not a small correction
    # apart: the nameplate judges a winter peak against a 30 C basis, while
    # K(T) credits the capability the cold ambient actually provides.
    k_curve = cold_capability_curve(temp, res_minutes=int(ANNUAL_RES_MINUTES))

    limits_by_conv: dict[str, dict[int, dict[str, Any]]] = {}
    triage: list[dict[str, Any]] = []
    for convention in TRIAGE_RATING_CONVENTIONS:
        curve = None if convention == "static" else k_curve
        lim = per_size_limits(
            base_mc, pools_by_size, rating_by_size, tday, hod0, k_curve=curve
        )
        limits_by_conv[convention] = lim
        for delta in TRIAGE_DISPERSION_GRID:
            for a in TRIAGE_ADOPTION_GRID:
                cell = triage_fleet(
                    homes_by_trafo,
                    lim,
                    a,
                    dispersion=float(delta),
                    draws=int(TRIAGE_CLUSTER_DRAWS),
                    seed=int(SEED) + int(round(float(delta) * 1000)) * 131,
                )
                cell["rating_convention"] = convention
                triage.append(cell)
    limits = limits_by_conv[TRIAGE_RATING_CONVENTIONS[0]]

    crf = capital_recovery_factor(float(DISCOUNT_RATE), int(LIFE_YEARS))
    pool_limited = sorted(
        h
        for conv in TRIAGE_RATING_CONVENTIONS
        for h in limits_by_conv[conv]
        if limits_by_conv[conv][h]["pool_limited"]
    )
    feeder_homes = homes_by_trafo[feeder_idx]

    payload: dict[str, Any] = {
        "n_transformers": len(homes_by_trafo),
        "n_homes": int(sum(homes_by_trafo.values())),
        "feeder_homes": feeder_homes,
        "curtail_tolerance": float(TRIAGE_CURTAIL_TOLERANCE),
        "base_dispersion": float(TRIAGE_BASE_DISPERSION),
        "dispersion_grid": [float(x) for x in TRIAGE_DISPERSION_GRID],
        "k_base": int(TRIAGE_K_BASE),
        "pool_per_home": float(TRIAGE_POOL_PER_HOME),
        "crf": round(crf, 6),
        "rating_conventions": list(TRIAGE_RATING_CONVENTIONS),
        "hotspot_limit_c": float(TRIAGE_HOTSPOT_LIMIT_C),
        "k_curve_summary": {
            "min": round(float(k_curve.min()), 4),
            "max": round(float(k_curve.max()), 4),
            "mean": round(float(k_curve.mean()), 4),
        },
        "by_size": {
            conv: {str(h): limits_by_conv[conv][h] for h in sorted(sizes)}
            for conv in TRIAGE_RATING_CONVENTIONS
        },
        "triage": triage,
        "pool_limited_sizes": pool_limited,
        "reference_feeder": limits[feeder_homes],
    }
    json_dir = PROJECT_OUTPUTS_DIR / "json"
    json_dir.mkdir(parents=True, exist_ok=True)
    out_path = json_dir / "fleet_triage.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    ref = payload["reference_feeder"]
    at_ref = next(
        (
            t
            for t in triage
            if abs(t["adoption_ev_per_home"] - 1.0) < 1e-9
            and abs(t["dispersion"] - float(TRIAGE_BASE_DISPERSION)) < 1e-9
            and t["rating_convention"] == TRIAGE_RATING_CONVENTIONS[0]
        ),
        triage[0],
    )
    at_uniform = next(
        (
            t
            for t in triage
            if abs(t["adoption_ev_per_home"] - 1.0) < 1e-9
            and abs(t["dispersion"]) < 1e-9
            and t["rating_convention"] == TRIAGE_RATING_CONVENTIONS[0]
        ),
        triage[0],
    )
    payload["artifact_paths"] = [out_path] + _figures(payload)
    payload["summary"] = {
        "n_transformers": payload["n_transformers"],
        "n_at_risk_at_1ev": at_ref["n_at_risk"],
        "flex_defers_at_1ev": at_ref["flex_defers"],
        "needs_steel_at_1ev": at_ref["needs_steel"],
        "base_constrained_at_1ev": at_ref["base_constrained"],
        "deferred_fraction_at_1ev": at_ref["deferred_fraction_of_at_risk"],
        "deferred_capex_usd_at_1ev": at_ref["deferred_capex_usd"],
        "feeder_firm_ev_count": ref["firm_ev_count"],
        "feeder_flexible_ev_count": ref["flexible_ev_count"],
        "feeder_curtailed_fraction_at_flexible": ref["curtailed_fraction_at_flexible"],
        "n_pool_limited_sizes": len(pool_limited),
        "base_dispersion": float(TRIAGE_BASE_DISPERSION),
        "flex_defers_at_1ev_uniform": at_uniform["flex_defers"],
        "n_at_risk_at_1ev_uniform": at_uniform["n_at_risk"],
    }
    return payload


def _figures(payload: dict[str, Any]) -> list[Path]:
    """Emit the triage stack and the per-size hosting limits."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir = PROJECT_OUTPUTS_DIR / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    base_delta = float(payload["base_dispersion"])
    conv0 = payload["rating_conventions"][0]
    tri = [
        t
        for t in payload["triage"]
        if abs(t["dispersion"] - base_delta) < 1e-9 and t["rating_convention"] == conv0
    ]
    adopt = [t["adoption_ev_per_home"] for t in tri]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.5, 4.6))
    ax1.stackplot(
        adopt,
        [t["never_binds"] for t in tri],
        [t["flex_defers"] for t in tri],
        [t["needs_steel"] for t in tri],
        [t["base_constrained"] for t in tri],
        labels=[
            "never binds",
            "flexibility defers",
            "needs steel (EV-driven)",
            "base-constrained (heating)",
        ],
        colors=["#cfe8cf", "#7fb3d5", "#e59866", "#c0392b"],
    )
    ax1.set_xlabel("EV adoption (EV per home)")
    ax1.set_ylabel("pole transformers")
    ax1.set_title(
        f"Fleet triage ({payload['n_transformers']} transformers), "
        f"clustered adoption sigma={base_delta}"
    )
    ax1.legend(loc="lower left", fontsize=8)

    at1 = sorted(
        (
            t
            for t in payload["triage"]
            if abs(t["adoption_ev_per_home"] - 1.0) < 1e-9
            and t["rating_convention"] == conv0
        ),
        key=lambda t: t["dispersion"],
    )
    del_x = [t["dispersion"] for t in at1]
    ax2.plot(del_x, [t["never_binds"] for t in at1], "o-", label="never binds")
    ax2.plot(del_x, [t["flex_defers"] for t in at1], "s-", label="flexibility defers")
    ax2.plot(del_x, [t["needs_steel"] for t in at1], "^-", label="needs steel")
    ax2.axvline(base_delta, ls=":", c="k", lw=1)
    ax2.set_xlabel("adoption dispersion (lognormal sigma)")
    ax2.set_ylabel("pole transformers")
    ax2.set_title("Effect of adoption clustering at 1 EV/home")
    ax2.legend(fontsize=8)
    ax2.grid(alpha=0.3)

    fig.tight_layout()
    path = figures_dir / "fleet_triage.png"
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return [path]


def run_stage() -> dict[str, Any]:
    """Run the fleet triage and emit the platform report."""
    from gridalyn.projects.scripting import project_script

    script = project_script()
    derived = derive_fleet_triage(script.cache_dir, PROJECT_OUTPUTS_DIR / "data")
    warnings = [
        "FLEXIBLE COUNT IS GATED ON THE CURTAILMENT TOLERANCE, not on "
        "feasibility. Under full enrollment the backstop can always hold a "
        "feeder (it curtails more), so the `residual_hours <= base_floor` gate "
        "used by apply_curtailment_contracts is near-vacuous and its reported "
        "flexible count equalled POOL_MAX_ANNUAL -- a pool-size artefact. The "
        "binding limit is the service denied to the customer, a commercial term.",
        "BASE-CONSTRAINED ASSETS CANNOT BE DEFERRED BY AN EV CONTRACT and are "
        "reported in their OWN category, checked BEFORE the EV counts. Where "
        "winter heating alone already exceeds the rating there is no EV load to "
        "shed in those hours, so enrollment cannot help however large the "
        "flexible count looks. Read the deferred fraction against n_at_risk, "
        f"never against the fleet size. Tolerance: "
        f"{float(TRIAGE_BASE_FLOOR_TOLERANCE_H)} base-alone overload hours; the "
        "per-size base_floor_hours are emitted so a laxer threshold can be "
        "applied without re-running.",
        "CLUSTERED ADOPTION IS THE BASE CASE, uniform is the reference. EV "
        "ownership is spatially correlated, so at a fixed fleet total a uniform "
        "allocation understates the worst last-mile transformer. The headline "
        f"uses sigma={float(TRIAGE_BASE_DISPERSION)}; the full dispersion grid "
        "is emitted so the sensitivity is readable rather than assumed.",
        "kW-proxy (power/thermal): no AC voltage or phase imbalance. Per-size "
        "MC with finite K_BASE -> the counts are medians carrying sampling "
        "error, and transformers of equal home count share a realization family.",
    ]
    if derived["pool_limited_sizes"]:
        warnings.append(
            "POOL-LIMITED SIZES "
            f"{derived['pool_limited_sizes']}: the curtailment tolerance never "
            "bound within the searched pool, so their flexible count is a LOWER "
            "BOUND. Raise TRIAGE_POOL_PER_HOME and re-run before citing them."
        )
    return script.write_report(
        "fleet_triage_report",
        artifacts=[script.file_reference(p) for p in derived["artifact_paths"]],
        summary=derived["summary"],
        validation={"valid": True, "errors": [], "warnings": warnings},
    )


def main() -> None:
    """CLI entry point for the fleet-triage stage."""
    argparse.ArgumentParser(description=__doc__).parse_args()
    report = run_stage()
    s = report.get("summary", {})
    print(
        f"Fleet triage + report: at 1 EV/home {s.get('flex_defers_at_1ev')}/"
        f"{s.get('n_at_risk_at_1ev')} at-risk transformers deferred by "
        f"flexibility ({s.get('deferred_fraction_at_1ev')}), "
        f"{s.get('needs_steel_at_1ev')} need steel | deferred capex "
        f"${s.get('deferred_capex_usd_at_1ev')} | reference feeder firm "
        f"{s.get('feeder_firm_ev_count')} -> flexible "
        f"{s.get('feeder_flexible_ev_count')} EVs"
    )


if __name__ == "__main__":
    main()
