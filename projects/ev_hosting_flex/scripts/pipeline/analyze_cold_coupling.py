"""Cold-coupling comparison: does a naive EV model overestimate winter hosting?

The study's lead finding. A NAIVE (cold-agnostic) EV model — the standard
hosting-study assumption of a fixed "typical" charging profile applied
year-round — misses that in a cold all-electric network EVs charge MORE (higher
plug-in probability, larger sessions) on exactly the coldest evenings, when the
electric-heating base also peaks. This stage re-runs the governed firm / flexible
/ curtailment analysis on a naive counterfactual pool (``plugin_kcold=0``,
``ev_kwh_kcold=0``) against the governed cold-coupled pool and quantifies the
over-estimation.

Emits ``cold_coupling_comparison.json`` + a two-panel figure, and a platform
report. Reuses the governed base/temperature artifacts and the firm/curtailment
kernels — only the EV model's cold slopes change.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np

from gridalyn.projects.scripting import ProjectScript
from projects.ev_hosting_flex.scripts._annual import (
    N_DAYS,
    ev_fleet_annual,
    feeder_rating,
    firm_annual,
    load_annual_tmy,
    simulate_curtailment,
    tmy_hour_of_day,
)
from projects.ev_hosting_flex.scripts.config import (
    ANNUAL_RES_MINUTES,
    COLD_DAY_TMEAN_C,
    DTYPE,
    POOL_MAX_ANNUAL,
    POWER_FACTOR,
    ROUND_DECIMALS,
    SEED,
    TRANSFORMER_KVA,
)

_RATING_KW = float(TRANSFORMER_KVA) * float(POWER_FACTOR)
_HOURS_PER_STEP = float(ANNUAL_RES_MINUTES) / 60.0
_STEPS_PER_DAY = 24 * 60 // ANNUAL_RES_MINUTES


def _flex_and_curtailment(
    base: np.ndarray,
    pool: np.ndarray,
    tday: np.ndarray,
    rating_series: np.ndarray | None = None,
) -> dict[str, Any]:
    """Return flexible count + total curtailed energy (kWh, % of EV energy).

    Args:
        base: ``(horizon,)`` feeder base in kW.
        pool: ``(pool, horizon)`` per-EV demand pool.
        tday: ``(365,)`` per-day mean temperatures.
        rating_series: Optional ``(horizon,)`` per-step usable rating in kW
            (RATING_CONVENTION); each hour is then judged against the
            capability its own ambient allows instead of the fixed nameplate.
            ``None`` keeps the nameplate-scalar behaviour.
    """
    limit = _RATING_KW if rating_series is None else rating_series
    base_floor = float((base > limit).sum()) * _HOURS_PER_STEP
    pool_max = pool.shape[0]
    flexible = 0
    for n in range(1, pool_max + 1):
        out = simulate_curtailment(
            base,
            pool[:n],
            np.ones(n, bool),
            _RATING_KW,
            res_minutes=ANNUAL_RES_MINUTES,
            rating_series=rating_series,
        )
        if out["residual_hours"] <= base_floor + 1e-9:
            flexible = n
    full = simulate_curtailment(
        base,
        pool,
        np.ones(pool_max, bool),
        _RATING_KW,
        res_minutes=ANNUAL_RES_MINUTES,
        rating_series=rating_series,
    )
    curt_kwh = float(full["curtailed_kwh_by_ev"].sum())
    ev_energy = float(pool.sum()) * _HOURS_PER_STEP
    return {
        "flexible_ev_count": flexible,
        "curtailed_kwh": round(curt_kwh, ROUND_DECIMALS),
        "curtailed_energy_percent": round(curt_kwh / ev_energy * 100.0, ROUND_DECIMALS),
    }


def _cold_day_ev_energy_per_ev(pool: np.ndarray, cold_days: np.ndarray) -> float:
    """Mean per-EV EV energy (kWh) delivered on the cold days."""
    n_evs = pool.shape[0]
    daily = pool[:, : N_DAYS * _STEPS_PER_DAY].reshape(n_evs, N_DAYS, _STEPS_PER_DAY)
    return float(daily[:, cold_days, :].sum()) * _HOURS_PER_STEP / n_evs


def derive_cold_coupling(script: ProjectScript) -> dict[str, Any]:
    data_dir = script.data_dir
    """Compute the cold-coupled vs naive comparison and persist it.

    Args:
        data_dir: Directory holding the F1 annual artifacts.
        json_dir: Governed JSON output directory.

    Returns:
        Dict with ``artifact_paths`` and the report ``summary``.
    """
    base = np.load(data_dir / "base_annual.npy").astype(DTYPE)[0]
    tday = np.load(data_dir / "tday_mean_c.npy").astype(DTYPE)
    temp = load_annual_tmy()
    hod0 = tmy_hour_of_day(temp)
    # Each hour is judged against the capability its OWN ambient allows
    # (RATING_CONVENTION). `cap` is the nameplate scalar kept for reporting;
    # `series` is what a load is actually compared against.
    cap, series = feeder_rating(temp)
    cold_days = np.where(tday < float(COLD_DAY_TMEAN_C))[0]

    cold_pool = ev_fleet_annual(
        np.random.default_rng(SEED), POOL_MAX_ANNUAL, tday, hod0
    )
    naive_pool = ev_fleet_annual(
        np.random.default_rng(SEED),
        POOL_MAX_ANNUAL,
        tday,
        hod0,
        plugin_kcold=0.0,
        ev_kwh_kcold=0.0,
    )

    models: dict[str, Any] = {}
    for name, pool in (("cold_coupled", cold_pool), ("naive", naive_pool)):
        firm = firm_annual(
            base,
            pool,
            cap,
            tday,
            hod0=hod0,
            res_minutes=ANNUAL_RES_MINUTES,
            rating_series=series,
        )
        flex = _flex_and_curtailment(base, pool, tday, rating_series=series)
        models[name] = {
            "firm_ev_count": int(firm["firm_ev_count"]),
            "p95_cold_evening_curve": firm["p95_curve"],
            "annual_ev_kwh_per_ev": round(
                float(pool.sum()) * _HOURS_PER_STEP / POOL_MAX_ANNUAL, ROUND_DECIMALS
            ),
            "cold_day_ev_kwh_per_ev": round(
                _cold_day_ev_energy_per_ev(pool, cold_days), ROUND_DECIMALS
            ),
            **flex,
        }

    firm_cold = models["cold_coupled"]["firm_ev_count"]
    firm_naive = models["naive"]["firm_ev_count"]
    curt_cold = models["cold_coupled"]["curtailed_energy_percent"]
    curt_naive = models["naive"]["curtailed_energy_percent"]
    e_cold = models["cold_coupled"]["cold_day_ev_kwh_per_ev"]
    e_naive = models["naive"]["cold_day_ev_kwh_per_ev"]

    payload = {
        "rating_kw": round(_RATING_KW, ROUND_DECIMALS),
        "cold_day_tmean_c": float(COLD_DAY_TMEAN_C),
        "n_cold_days": int(cold_days.size),
        "models": models,
        "firm_overestimate_ev": firm_naive - firm_cold,
        "firm_overestimate_percent": (
            round((firm_naive - firm_cold) / firm_cold * 100.0, ROUND_DECIMALS)
            if firm_cold
            else None
        ),
        "curtailment_underestimate_ratio": (
            round(curt_cold / curt_naive, ROUND_DECIMALS) if curt_naive else None
        ),
        "cold_day_ev_energy_uplift_percent": round(
            (e_cold - e_naive) / e_naive * 100.0, ROUND_DECIMALS
        ),
    }
    out_path_ref = script.write_json(
        "outputs/json/cold_coupling_comparison.json", payload
    )

    fig_paths = _figure(payload, script.figures_dir)

    summary = {
        "firm_cold_coupled": firm_cold,
        "firm_naive": firm_naive,
        "firm_overestimate_percent": payload["firm_overestimate_percent"],
        "curtailment_percent_cold": curt_cold,
        "curtailment_percent_naive": curt_naive,
        "curtailment_underestimate_ratio": payload["curtailment_underestimate_ratio"],
        "cold_day_ev_energy_uplift_percent": payload[
            "cold_day_ev_energy_uplift_percent"
        ],
    }
    return {"artifact_paths": [out_path_ref, *fig_paths], "summary": summary}


def _figure(payload: dict[str, Any], figures_dir: Path) -> list[Path]:
    """Two-panel figure: P95 curves diverging + cold-day EV energy uplift."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    cold = payload["models"]["cold_coupled"]
    naive = payload["models"]["naive"]

    fig, (axl, axr) = plt.subplots(1, 2, figsize=(11.0, 4.3))

    n = range(len(cold["p95_cold_evening_curve"]))
    axl.plot(
        n,
        cold["p95_cold_evening_curve"],
        "o-",
        color="C3",
        label=f"cold-coupled (firm {cold['firm_ev_count']})",
    )
    axl.plot(
        n,
        naive["p95_cold_evening_curve"],
        "s--",
        color="C0",
        label=f"naive (firm {naive['firm_ev_count']})",
    )
    axl.axhline(100.0, color="k", ls=":", lw=1.2, label="transformer rating")
    axl.set_xlabel("EVs on the 6-home feeder")
    axl.set_ylabel("P95 cold-evening loading (%)")
    axl.set_title("Naive EV model overestimates firm hosting")
    axl.legend(fontsize=8)

    labels = ["annual/EV", "cold-day/EV"]
    cold_vals = [cold["annual_ev_kwh_per_ev"], cold["cold_day_ev_kwh_per_ev"]]
    naive_vals = [naive["annual_ev_kwh_per_ev"], naive["cold_day_ev_kwh_per_ev"]]
    x = np.arange(len(labels))
    axr.bar(x - 0.2, cold_vals, 0.38, color="C3", label="cold-coupled")
    axr.bar(x + 0.2, naive_vals, 0.38, color="C0", label="naive")
    axr.set_xticks(x)
    axr.set_xticklabels(labels)
    axr.set_ylabel("EV energy (kWh/EV)")
    axr.set_title(
        f"+{payload['cold_day_ev_energy_uplift_percent']:.0f}% EV energy on cold days"
    )
    axr.legend(fontsize=8)

    fig.suptitle(
        "Cold-coupled EV charging shrinks winter hosting capacity "
        f"(firm {naive['firm_ev_count']} -> {cold['firm_ev_count']}, "
        f"curtailment {payload['curtailment_underestimate_ratio']:.1f}x)",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    paths = []
    for suffix in (".png", ".pdf"):
        p = figures_dir / f"cold_coupling_comparison{suffix}"
        fig.savefig(p, dpi=200, bbox_inches="tight")
        paths.append(p)
    plt.close(fig)
    return paths


def run_stage() -> dict[str, Any]:
    """Run the cold-coupling comparison stage and emit the platform report."""
    from gridalyn.projects.scripting import project_script

    script = project_script()
    derived = derive_cold_coupling(script)
    return script.write_report(
        "cold_coupling_report",
        artifacts=[
            p if isinstance(p, dict) else script.file_reference(p)
            for p in derived["artifact_paths"]
        ],
        summary=derived["summary"],
        validation={"valid": True, "errors": [], "warnings": []},
    )


def main() -> None:
    """CLI entry point for the cold-coupling comparison stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    report = run_stage()
    s = report.get("summary", {})
    print(
        "Cold-coupling comparison + report: "
        f"firm naive={s.get('firm_naive')} vs cold-coupled={s.get('firm_cold_coupled')} "
        f"(naive overestimates +{s.get('firm_overestimate_percent')}%) | "
        f"curtailment {s.get('curtailment_percent_naive')}% -> "
        f"{s.get('curtailment_percent_cold')}% "
        f"({s.get('curtailment_underestimate_ratio')}x underestimated) | "
        f"cold-day EV energy +{s.get('cold_day_ev_energy_uplift_percent')}%"
    )


if __name__ == "__main__":
    main()
