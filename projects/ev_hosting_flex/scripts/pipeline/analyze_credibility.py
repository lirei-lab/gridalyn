"""Credibility layer: confidence intervals on the study headlines.

Re-runs the firm/flex/breakeven headline chain over CREDIBILITY_K realizations that
vary the building seed (SEED+r), the EV-fleet seed (SEED+CREDIBILITY_EV_SALT*r), and
a synthetic winter-severity temperature anomaly (delta_r ~ N(0, WEATHER_SIGMA_C),
delta_0 = 0). Reports P5/P50/P95 + mode + P(=governed point) per headline. Realization
0 (delta_0=0, SEED) reproduces the governed point (a consistency guard). kW-proxy; no
SDK edit; the heavy K-realization base generation runs in the main session.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, cast

import numpy as np

from gridalyn.foundation.platform.uncertainty import (
    UncertaintyEstimate,
    build_uncertainty,
)
from gridalyn.projects.scripting import ProjectScript
from projects.ev_hosting_flex.scripts._annual import (
    N_DAYS,
    annual_base_realization,
    day_mean_temps,
    ev_fleet_annual,
    feeder_rating,
    firm_annual,
    load_annual_tmy,
    simulate_curtailment,
    tmy_hour_of_day,
)
from projects.ev_hosting_flex.scripts.config import (
    ANNUAL_RES_MINUTES,
    C_A_CURTAIL,
    C_AVAIL_EV_YR,
    CAPEX_UPGRADE,
    CREDIBILITY_EV_SALT,
    CREDIBILITY_K,
    CREDIBILITY_WEATHER_SALT,
    DISCOUNT_RATE,
    DTYPE,
    LIFE_YEARS,
    POOL_MAX_ANNUAL,
    POWER_FACTOR,
    ROUND_DECIMALS,
    SEED,
    TRANSFORMER_KVA,
    WEATHER_SIGMA_C,
)
from projects.ev_hosting_flex.scripts.pipeline.compute_curtailment_economics import (
    capital_recovery_factor,
)
from projects.ev_hosting_flex.scripts.pipeline.generate_annual_mc import (
    feeder_home_count,
)

_RATING_KW = float(TRANSFORMER_KVA) * float(POWER_FACTOR)


def winter_offsets(k: int, sigma: float, salt: int) -> np.ndarray:
    """K winter-severity temperature anomalies (deg C); ``[0]`` forced to 0 (the
    nominal-weather anchor), the rest drawn N(0, sigma) from a salted rng."""
    rng = np.random.default_rng(int(SEED) + int(salt))
    out = np.zeros(int(k), dtype=DTYPE)
    if k > 1:
        out[1:] = rng.normal(0.0, float(sigma), int(k) - 1).astype(DTYPE)
    return out


def _flex_count(
    base: np.ndarray,
    pool: np.ndarray,
    rating: float,
    res: int,
    rating_series: np.ndarray | None = None,
) -> int:
    """Largest pool prefix n whose full-enrollment curtailment holds residual
    congestion at the base floor (mirrors apply_curtailment_contracts).

    Args:
        base: Feeder base load (kW).
        pool: Per-EV demand pool (kW), prefix-swept.
        rating: Feeder usable rating (kW).
        res: Step width in minutes.
        rating_series: Optional per-step usable rating (kW) overriding the
            scalar ``rating`` (RATING_CONVENTION); ``None`` keeps the scalar
            behaviour.
    """
    limit = rating if rating_series is None else rating_series
    base_floor = float((base > limit).sum()) * (res / 60.0)
    flexible = 0
    for n in range(1, pool.shape[0] + 1):
        out = simulate_curtailment(
            base,
            pool[:n],
            np.ones(n, dtype=bool),
            rating,
            res_minutes=res,
            rating_series=rating_series,
        )
        if float(out["residual_hours"]) <= base_floor + 1e-9:
            flexible = n
    return flexible


def _breakeven_count(
    base: np.ndarray,
    pool: np.ndarray,
    rating: float,
    res: int,
    crf: float,
    rating_series: np.ndarray | None = None,
) -> int:
    """Last pool prefix n where the flex contract still beats the annualized
    reinforcement (mirrors compute_curtailment_economics).

    Args:
        base: Feeder base load (kW).
        pool: Per-EV demand pool (kW), prefix-swept.
        rating: Feeder usable rating (kW).
        res: Step width in minutes.
        crf: Capital recovery factor annualizing ``CAPEX_UPGRADE``.
        rating_series: Optional per-step usable rating (kW) overriding the
            scalar ``rating`` (RATING_CONVENTION); ``None`` keeps the scalar
            behaviour.
    """
    reinf_annual = float(CAPEX_UPGRADE) * float(crf)
    breakeven = 0
    for n in range(1, pool.shape[0] + 1):
        out = simulate_curtailment(
            base,
            pool[:n],
            np.ones(n, dtype=bool),
            rating,
            res_minutes=res,
            rating_series=rating_series,
        )
        curt_kwh = float(np.sum(out["curtailed_kwh_by_ev"]))
        contract = n * float(C_AVAIL_EV_YR) + float(C_A_CURTAIL) * curt_kwh
        if contract <= reinf_annual:
            breakeven = n
    return breakeven


def realization_headlines(
    base: np.ndarray,
    pool: np.ndarray,
    tday: np.ndarray,
    rating: float,
    res: int,
    hod0: int,
    rating_series: np.ndarray | None = None,
) -> dict[str, Any]:
    """firm/flex/breakeven/base_peak/curtailed_pct for one realization. ``hod0``
    is the LOCAL phase anchor (threaded so r=0 reproduces the governed firm).

    Args:
        base: Feeder base load (kW).
        pool: Per-EV demand pool (kW), prefix-swept.
        tday: Per-day mean temperatures (365,).
        rating: Feeder usable rating (kW).
        res: Step width in minutes.
        hod0: LOCAL hour-of-day phase anchor.
        rating_series: Optional per-step usable rating (kW) overriding the
            scalar ``rating`` (RATING_CONVENTION): each hour is judged
            against the capability its OWN ambient allows rather than the
            30 °C nameplate. ``None`` keeps the scalar behaviour exactly.
    """
    firm = int(
        firm_annual(
            base,
            pool,
            rating,
            tday,
            hod0=int(hod0),
            res_minutes=res,
            rating_series=rating_series,
        )["firm_ev_count"]
    )
    flex = _flex_count(base, pool, rating, res, rating_series=rating_series)
    crf = capital_recovery_factor(float(DISCOUNT_RATE), int(LIFE_YEARS))
    breakeven = _breakeven_count(
        base, pool, rating, res, crf, rating_series=rating_series
    )
    full = simulate_curtailment(
        base,
        pool,
        np.ones(pool.shape[0], dtype=bool),
        rating,
        res_minutes=res,
        rating_series=rating_series,
    )
    total_ev = float(np.sum(pool)) * (res / 60.0)
    curt_kwh = float(np.sum(full["curtailed_kwh_by_ev"]))
    return {
        "firm": firm,
        "flex": flex,
        "breakeven": breakeven,
        "base_peak": round(float(base.max()), ROUND_DECIMALS),
        "curtailed_pct": round(
            100.0 * curt_kwh / total_ev if total_ev > 0 else 0.0, ROUND_DECIMALS
        ),
    }


def _stats(samples: list[float], point: float | None = None) -> dict[str, Any]:
    """P5/P50/P95 + mean/std + mode + P(=point) for one headline's K samples."""
    arr = np.array(samples, dtype=DTYPE)
    vals, counts = np.unique(arr, return_counts=True)
    mode = float(vals[int(np.argmax(counts))])
    out = {
        "p05": round(float(np.percentile(arr, 5)), ROUND_DECIMALS),
        "p50": round(float(np.percentile(arr, 50)), ROUND_DECIMALS),
        "p95": round(float(np.percentile(arr, 95)), ROUND_DECIMALS),
        "mean": round(float(arr.mean()), ROUND_DECIMALS),
        "std": round(float(arr.std()), ROUND_DECIMALS),
        "mode": round(mode, ROUND_DECIMALS),
    }
    if point is not None:
        out["p_at_point"] = round(float((arr == point).mean()), ROUND_DECIMALS)
    return out


#: Coverage of the P5-P95 band this stage reports. Stated here rather than
#: left for a reader to infer from two percentile keys.
CREDIBILITY_LEVEL = 0.90

#: The pinned study seed as an ``int``. ``config.SEED`` reaches here typed
#: ``object`` because it is read from the YAML contract -- the shape most of the
#: projects mypy backlog is made of. Narrowed once here rather than at each use,
#: so recording the seed in the report does not add to that backlog.
SEED_INT: int = cast(int, SEED)


def _estimate(
    metric: str, stats: dict[str, Any], k: int, note: str
) -> UncertaintyEstimate:
    """Turn one headline's P5/P50/P95 into a contract uncertainty estimate.

    Built from the percentiles the summary already carries rather than
    recomputed, so the interval and the number it qualifies cannot drift apart
    through rounding.

    Args:
        metric: The summary key this estimate qualifies.
        stats: The ``_stats`` payload for that headline.
        k: The number of realizations behind the distribution.
        note: What the draws vary.

    Returns:
        The estimate, at :data:`CREDIBILITY_LEVEL` coverage.
    """
    return UncertaintyEstimate(
        metric=metric,
        method="monte_carlo",
        n=k,
        point=float(stats["p50"]),
        low=float(stats["p05"]),
        high=float(stats["p95"]),
        level=CREDIBILITY_LEVEL,
        seed=SEED_INT,
        note=note,
    )


def derive_credibility(script: ProjectScript) -> dict[str, Any]:
    """Run the K-realization headline chain and summarize the distributions."""
    n_homes = feeder_home_count(script)
    temp = load_annual_tmy()
    hod0 = int(tmy_hour_of_day(temp))
    tday = day_mean_temps(temp)
    res = int(ANNUAL_RES_MINUTES)
    # Each hour is judged against the capability its OWN ambient allows
    # (RATING_CONVENTION). `cap` is the nameplate scalar kept for reporting;
    # `series` is what a load is actually compared against in the kernels.
    cap, series = feeder_rating(temp)
    k = int(CREDIBILITY_K)
    offsets = winter_offsets(k, float(WEATHER_SIGMA_C), int(CREDIBILITY_WEATHER_SALT))

    samples: dict[str, list[float]] = {
        "firm": [],
        "flex": [],
        "breakeven": [],
        "base_peak": [],
        "curtailed_pct": [],
    }
    for r in range(k):
        delta = float(offsets[r])
        offset_arr = np.full(int(N_DAYS), delta, dtype=DTYPE)
        base_r = annual_base_realization(
            temp, int(n_homes), int(SEED) + r, per_day_offset_c=offset_arr
        )
        tday_r = tday + delta
        pool_r = ev_fleet_annual(
            np.random.default_rng(int(SEED) + int(CREDIBILITY_EV_SALT) * r),
            int(POOL_MAX_ANNUAL),
            tday_r,
            hod0,
        )
        h = realization_headlines(
            base_r, pool_r, tday_r, cap, res, hod0, rating_series=series
        )
        for key in samples:
            samples[key].append(float(h[key]))

    # point estimates = realization 0 (delta=0, SEED) — the governed anchor
    firm_stats = _stats(samples["firm"], point=samples["firm"][0])
    flex_stats = _stats(samples["flex"], point=samples["flex"][0])
    be_stats = _stats(samples["breakeven"], point=samples["breakeven"][0])
    payload = {
        "k": k,
        "weather_sigma_c": float(WEATHER_SIGMA_C),
        "n_homes": int(n_homes),
        "rating_kw": round(_RATING_KW, ROUND_DECIMALS),
        "samples": {
            key: [round(v, ROUND_DECIMALS) for v in vals]
            for key, vals in samples.items()
        },
        "firm": firm_stats,
        "flex": flex_stats,
        "breakeven": be_stats,
        "base_peak": _stats(samples["base_peak"]),
        "curtailed_pct": _stats(samples["curtailed_pct"]),
        "point_realization_0": {k2: samples[k2][0] for k2 in samples},
    }
    json_ref = script.write_json("outputs/json/credibility.json", payload)
    fig_paths = _figures(payload, script.figures_dir)
    summary = {
        "firm_p05": firm_stats["p05"],
        "firm_p50": firm_stats["p50"],
        "firm_p95": firm_stats["p95"],
        "flex_p05": flex_stats["p05"],
        "flex_p50": flex_stats["p50"],
        "flex_p95": flex_stats["p95"],
        "breakeven_p50": be_stats["p50"],
        "base_peak_p50": payload["base_peak"]["p50"],
    }
    # The K-realization distribution behind these percentiles was previously
    # reported as loose p05/p50/p95 keys, with the method, the sample count,
    # the coverage and the seed left for a reader to infer. The contract block
    # states them.
    axes = "building seed, EV-fleet seed and a synthetic winter-severity anomaly"
    uncertainty = build_uncertainty(
        [
            _estimate("firm_p50", firm_stats, k, f"varies {axes}"),
            _estimate("flex_p50", flex_stats, k, f"varies {axes}"),
            _estimate("breakeven_p50", be_stats, k, f"varies {axes}"),
            _estimate("base_peak_p50", payload["base_peak"], k, f"varies {axes}"),
        ]
    )
    return {
        "artifact_paths": [json_ref, *fig_paths],
        "summary": summary,
        "uncertainty": uncertainty,
    }


def _figures(payload: dict[str, Any], figures_dir: Path) -> list[Path]:
    """Box-plots of firm/flex/breakeven + the base-peak distribution."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.0, 4.3))
    s = payload["samples"]
    ax1.boxplot(
        [s["firm"], s["flex"], s["breakeven"]],
        tick_labels=["firm", "flex", "breakeven"],
    )
    ax1.set_ylabel("EV count")
    ax1.set_title(f"Headline distributions (K={payload['k']})")
    ax2.hist(s["base_peak"], bins=15, color="C0", alpha=0.8)
    ax2.axvline(payload["rating_kw"], color="k", ls="--", lw=1, label="rating")
    ax2.set_xlabel("base peak (kW)")
    ax2.set_ylabel("realizations")
    ax2.set_title("Base-peak distribution")
    ax2.legend(fontsize=8)
    fig.suptitle(
        "Credibility: headline confidence intervals (seed x winter severity)",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    paths = []
    for suffix in (".png", ".pdf"):
        p = figures_dir / f"credibility{suffix}"
        fig.savefig(p, dpi=200, bbox_inches="tight")
        paths.append(p)
    plt.close(fig)
    return paths


def run_stage() -> dict[str, Any]:
    """Run the credibility stage and emit the platform report."""
    from gridalyn.projects.scripting import project_script

    script = project_script()
    derived = derive_credibility(script)
    warnings = [
        "CREDIBILITY layer: confidence intervals on the pilar-1 headlines "
        "(firm/flex/breakeven) over K realizations varying the building/EV seeds "
        "and a synthetic winter-severity temperature anomaly.",
        "SINGLE TMY: the weather axis is a SYNTHETIC winter-severity proxy (uniform "
        "per-day N(0, sigma) offset), NOT measured inter-annual weather years.",
        "Realization 0 (delta=0, SEED) reproduces the governed point estimate (a "
        "consistency anchor). Governed feeder / pilar-1 trio only; K finite -> the "
        "P5/P95 tails carry sampling error.",
    ]
    return script.write_report(
        "credibility_report",
        artifacts=[
            p if isinstance(p, dict) else script.file_reference(p)
            for p in derived["artifact_paths"]
        ],
        summary=derived["summary"],
        uncertainty=derived["uncertainty"],
        validation={"valid": True, "errors": [], "warnings": warnings},
    )


def main() -> None:
    """CLI entry point for the credibility stage."""
    argparse.ArgumentParser(description=__doc__).parse_args()
    report = run_stage()
    s = report.get("summary", {})
    print(
        f"Credibility + report: firm P50 {s.get('firm_p50')} "
        f"[{s.get('firm_p05')}, {s.get('firm_p95')}] | flex P50 {s.get('flex_p50')} "
        f"[{s.get('flex_p05')}, {s.get('flex_p95')}] | breakeven P50 "
        f"{s.get('breakeven_p50')} | base peak P50 {s.get('base_peak_p50')} kW"
    )


if __name__ == "__main__":
    main()
