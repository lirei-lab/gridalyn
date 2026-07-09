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
    INCENTIVE_TARGET_EV_PER_HOME,
    POOL_TILES,
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
) -> float:
    """P95 over the bin's days of the WHOLE-DAY peak loading (% of rating).

    The peak is taken over all 24 hours, NOT just the evening window: the
    ``shift`` policy moves EV load into the overnight hours, so an evening-only
    metric would credit shift with spurious "relief" while it dumps load into
    unmonitored overnight hours (which can themselves exceed the rating). The
    transformer can overload at any hour, so the constraint is the 24-hour max.

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

    Returns:
        The P95 (over the bin's days) whole-day peak loading, in percent.
    """
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
            flex_agg = valley_fill_shift(
                base_day + free_agg,
                enrolled.sum(axis=1),  # per-EV daily energy (kWh)
                rating_kw,
                charger_kw[:n_enrolled],
            )
        else:
            raise ValueError(f"unknown policy {policy!r}")
        total = base_day + free_agg + flex_agg
        peaks.append(float(total.max()))
    return float(
        np.percentile(np.array(peaks, dtype=DTYPE) / float(rating_kw) * 100.0, 95)
    )


def _min_enrollment_feasible(
    *, base, pool, day_indices, n_ev, policy, rating_kw, hod0, charger_kw
) -> int | None:
    """Smallest enrolled count (0..n_ev) with P95 <= 100%, or None if infeasible."""
    for e in range(0, n_ev + 1):
        p95 = _bin_p95_loading(
            base=base, pool=pool, day_indices=day_indices, n_ev=n_ev,
            n_enrolled=e, policy=policy, rating_kw=rating_kw, hod0=hod0,
            charger_kw=charger_kw,
        )
        if p95 <= 100.0:
            return e
    return None


def _optimize_bin(
    *, base, pool, bin_entry, n_ev, rating_kw, hod0, charger_kw
) -> dict[str, Any]:
    """Return the min-subsidy feasible policy for one climate bin."""
    day_indices = bin_entry["day_indices"]
    p95_unc = _bin_p95_loading(
        base=base, pool=pool, day_indices=day_indices, n_ev=n_ev, n_enrolled=0,
        policy="uncontrolled", rating_kw=rating_kw, hod0=hod0, charger_kw=charger_kw,
    )
    options: dict[str, dict[str, Any]] = {}
    for policy, med, sig in (
        ("shift", float(WTA_SHIFT_MEDIAN), float(WTA_SHIFT_SIGMA)),
        ("curtail", float(WTA_CURTAIL_MEDIAN), float(WTA_CURTAIL_SIGMA)),
    ):
        e_star = _min_enrollment_feasible(
            base=base, pool=pool, day_indices=day_indices, n_ev=n_ev,
            policy=policy, rating_kw=rating_kw, hod0=hod0, charger_kw=charger_kw,
        )
        if e_star is None:
            options[policy] = {
                "feasible": False, "subsidy": None, "enrolled": None,
                "incentive": None,
            }
            continue
        frac = e_star / n_ev if n_ev else 0.0
        price = wta_price_for_enrollment(frac, med, sig) if e_star > 0 else 0.0
        options[policy] = {
            "feasible": True,
            "enrolled": int(e_star),
            "incentive": round(price, ROUND_DECIMALS),
            "subsidy": round(price * e_star, ROUND_DECIMALS),
        }
    feasible = {k: v for k, v in options.items() if v["feasible"]}
    optimal = (
        min(feasible, key=lambda k: feasible[k]["subsidy"]) if feasible else None
    )
    return {
        "bin_lo": bin_entry["bin_lo"],
        "bin_hi": bin_entry["bin_hi"],
        "mean_temp_c": bin_entry["mean_temp_c"],
        "n_days": bin_entry["n_days"],
        "p95_uncontrolled": round(p95_unc, ROUND_DECIMALS),
        "binding": bool(p95_unc > 100.0),
        "options": options,
        "optimal_policy": optimal,
        "optimal_subsidy": feasible[optimal]["subsidy"] if optimal else None,
    }


def _policy_ceiling_ev_per_home(
    *, base, pool, day_indices, policy, rating_kw, hod0, charger_kw, n_max
) -> float:
    """Max EV/home (over the 6-home feeder) this policy hosts with P95 <= 100%.

    Searches the fleet size downward from ``n_max``; the ceiling / 6 is the
    per-home hosting limit. ``shift`` enrols the whole fleet; ``uncontrolled``
    enrols none. Returns ``n_max / 6`` if even the full pool stays feasible
    (pool-capped) — flagged by the caller.
    """
    for n in range(int(n_max), 0, -1):
        p95 = _bin_p95_loading(
            base=base, pool=pool, day_indices=day_indices, n_ev=n,
            n_enrolled=n if policy == "shift" else 0, policy=policy,
            rating_kw=rating_kw, hod0=hod0, charger_kw=charger_kw,
        )
        if p95 <= 100.0:
            return n / 6.0
    return 0.0


def _crossover_from_ceiling(
    bins: list[dict[str, Any]], target: float
) -> float | None:
    """Temperature where the shift-hosting ceiling drops through ``target``.

    Linear interpolation between the adjacent bins that bracket the target
    (ceiling below target on the cold side, at/above on the warm side).
    """
    ordered = sorted(bins, key=lambda b: b["mean_temp_c"])
    for cold, warm in zip(ordered[:-1], ordered[1:]):
        c0, c1 = cold["shift_ceiling_ev_per_home"], warm["shift_ceiling_ev_per_home"]
        if c0 < target <= c1:
            t0, t1 = cold["mean_temp_c"], warm["mean_temp_c"]
            if c1 == c0:
                return round(t1, ROUND_DECIMALS)
            return round(t0 + (target - c0) * (t1 - t0) / (c1 - c0), ROUND_DECIMALS)
    return None


def derive_incentive(data_dir: Path) -> dict[str, Any]:
    """Bin the year; per bin compute the shift-hosting ceiling + the incentive
    optimum at the high-adoption target; assemble the payload + figure."""
    base_h = aggregate_to_hourly(
        np.load(data_dir / "base_annual.npy").astype(DTYPE)
    )[0]
    pool_1 = aggregate_to_hourly(
        np.load(data_dir / "ev_fleet_annual.npy").astype(DTYPE)
    )
    # tile the homogeneous pool to sweep beyond 2 EV/home (the pool cap)
    pool_h = np.tile(pool_1, (int(POOL_TILES), 1)).astype(DTYPE)
    temp = load_annual_tmy()
    hod0 = int(tmy_hour_of_day(temp))
    charger_kw = pool_h.max(axis=1).astype(DTYPE)  # per-EV peak = charger rating
    n_max = pool_h.shape[0]
    target_ev_home = float(INCENTIVE_TARGET_EV_PER_HOME)
    n_target = min(int(round(target_ev_home * 6)), n_max)

    bin_entries = climate_bin_days(temp, CLIMATE_BIN_EDGES)
    results = []
    for be in bin_entries:
        res = _optimize_bin(
            base=base_h, pool=pool_h, bin_entry=be, n_ev=n_target,
            rating_kw=_RATING_KW, hod0=hod0, charger_kw=charger_kw,
        )
        shift_ceiling = _policy_ceiling_ev_per_home(
            base=base_h, pool=pool_h, day_indices=be["day_indices"],
            policy="shift", rating_kw=_RATING_KW, hod0=hod0,
            charger_kw=charger_kw, n_max=n_max,
        )
        unc_ceiling = _policy_ceiling_ev_per_home(
            base=base_h, pool=pool_h, day_indices=be["day_indices"],
            policy="uncontrolled", rating_kw=_RATING_KW, hod0=hod0,
            charger_kw=charger_kw, n_max=n_max,
        )
        res["shift_ceiling_ev_per_home"] = round(shift_ceiling, ROUND_DECIMALS)
        res["uncontrolled_ceiling_ev_per_home"] = round(unc_ceiling, ROUND_DECIMALS)
        res["shift_ceiling_pool_capped"] = bool(shift_ceiling >= n_max / 6.0)
        results.append(res)

    crossover = _crossover_from_ceiling(results, target_ev_home)
    ordered = sorted(results, key=lambda b: b["mean_temp_c"])
    coldest, warmest = ordered[0], ordered[-1]

    payload = {
        "target_ev_per_home": target_ev_home,
        "n_target": n_target,
        "pool_ev_max": n_max,
        "hod0": hod0,
        "rating_kw": round(_RATING_KW, ROUND_DECIMALS),
        "crossover_temp_c": crossover,
        "shift_ceiling_coldest": coldest["shift_ceiling_ev_per_home"],
        "shift_ceiling_warmest": warmest["shift_ceiling_ev_per_home"],
        "optimal_subsidy_coldest": coldest["optimal_subsidy"],
        "optimal_subsidy_warmest": warmest["optimal_subsidy"],
        "bins": results,
    }
    json_dir = PROJECT_OUTPUTS_DIR / "json"
    json_dir.mkdir(parents=True, exist_ok=True)
    out_path = json_dir / "flexibility_incentive.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    fig_paths = _figures(payload, PROJECT_OUTPUTS_DIR / "figures")
    summary = {
        "target_ev_per_home": target_ev_home,
        "crossover_temp_c": crossover,
        "shift_ceiling_coldest": coldest["shift_ceiling_ev_per_home"],
        "shift_ceiling_warmest": warmest["shift_ceiling_ev_per_home"],
        "optimal_subsidy_coldest": coldest["optimal_subsidy"],
        "optimal_subsidy_warmest": warmest["optimal_subsidy"],
        "coldest_optimal_policy": coldest["optimal_policy"],
        "warmest_optimal_policy": warmest["optimal_policy"],
    }
    return {"artifact_paths": [out_path, *fig_paths], "summary": summary}


def _figures(payload: dict[str, Any], figures_dir: Path) -> list[Path]:
    """Three-panel figure: physical stress, optimal incentive, subsidy by policy."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    bins = sorted(payload["bins"], key=lambda b: b["mean_temp_c"])
    temps = [b["mean_temp_c"] for b in bins]
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(14.5, 4.3))

    ax1.plot(
        temps, [b["shift_ceiling_ev_per_home"] for b in bins], "o-", color="C2",
        label="optimal shift",
    )
    ax1.plot(
        temps, [b["uncontrolled_ceiling_ev_per_home"] for b in bins], "s--",
        color="C0", label="uncontrolled",
    )
    ax1.axhline(payload["target_ev_per_home"], color="k", ls=":", lw=1,
                label=f"target {payload['target_ev_per_home']:g}")
    ax1.set_xlabel("bin mean temp (°C)")
    ax1.set_ylabel("Hosting ceiling (EV/home)")
    ax1.set_title("Shift-hosting ceiling falls with cold")
    ax1.legend(fontsize=8)

    colors = {"shift": "C2", "curtail": "C3", None: "0.6"}
    for b in bins:
        ax2.scatter(
            b["mean_temp_c"], b["optimal_subsidy"] or 0.0,
            color=colors.get(b["optimal_policy"]), s=40,
        )
    if payload["crossover_temp_c"] is not None:
        ax2.axvline(
            payload["crossover_temp_c"], color="k", ls=":", lw=1.5,
            label=f"crossover {payload['crossover_temp_c']:g} °C",
        )
        ax2.legend(fontsize=8)
    ax2.set_xlabel("bin mean temp (°C)")
    ax2.set_ylabel("Optimal subsidy ($/yr)")
    ax2.set_title("Optimal incentive: curtail (cold) → shift (warm)")

    for policy, c in (("shift", "C2"), ("curtail", "C3")):
        xs = [b["mean_temp_c"] for b in bins if b["options"][policy]["feasible"]]
        ys = [
            b["options"][policy]["subsidy"]
            for b in bins if b["options"][policy]["feasible"]
        ]
        ax3.plot(xs, ys, "o-", color=c, label=policy)
    ax3.set_xlabel("bin mean temp (°C)")
    ax3.set_ylabel("Subsidy by policy ($/yr)")
    ax3.set_title("Shift infeasible in the cold (no valley)")
    ax3.legend(fontsize=8)

    fig.suptitle(
        "Vanishing valley: the optimal flexibility incentive migrates with climate",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    paths = []
    for suffix in (".png", ".pdf"):
        p = figures_dir / f"flexibility_incentive{suffix}"
        fig.savefig(p, dpi=200, bbox_inches="tight")
        paths.append(p)
    plt.close(fig)
    return paths


def run_stage() -> dict[str, Any]:
    """Run the flexibility-incentive stage and emit the platform report."""
    from gridalyn.projects.scripting import project_script

    script = project_script()
    derived = derive_incentive(PROJECT_OUTPUTS_DIR / "data")
    warnings = [
        "WTA ILLUSTRATIVE: the willingness-to-accept curve (lognormal, config "
        "medians/sigmas) is a behavioural assumption, not calibrated — like the "
        "deck's enrollment lever. The CROSSOVER TEMPERATURE is robust (shift is "
        "physically infeasible in the cold regardless of WTA); the subsidy "
        "DOLLARS are illustrative.",
        "SCOPE: pure-kW on the governed 6-home/75 kVA feeder (static rating, "
        "24-hour peak), no AC. Real tariff-billing mechanics and phase imbalance "
        "are out of scope.",
    ]
    return script.write_report(
        "flexibility_incentive_report",
        artifacts=[script.file_reference(p) for p in derived["artifact_paths"]],
        summary=derived["summary"],
        validation={"valid": True, "errors": [], "warnings": warnings},
    )


def main() -> None:
    """CLI entry point for the flexibility-incentive stage."""
    argparse.ArgumentParser(description=__doc__).parse_args()
    report = run_stage()
    s = report.get("summary", {})
    print(
        "Flexibility incentive + report: shift-hosting ceiling "
        f"{s.get('shift_ceiling_coldest')} EV/home (cold) -> "
        f"{s.get('shift_ceiling_warmest')} (warm) | at target "
        f"{s.get('target_ev_per_home')} EV/home crossover at "
        f"{s.get('crossover_temp_c')} °C: coldest -> "
        f"{s.get('coldest_optimal_policy')} (${s.get('optimal_subsidy_coldest')}/yr), "
        f"warmest -> {s.get('warmest_optimal_policy')} "
        f"(${s.get('optimal_subsidy_warmest')}/yr)"
    )


if __name__ == "__main__":
    main()
