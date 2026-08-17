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
import pickle
from pathlib import Path
from typing import Any

import numpy as np

from gridalyn.projects.scripting import ProjectScript
from projects.ev_hosting_flex.scripts._annual import (
    aggregate_to_hourly,
    climate_bin_days,
    load_annual_tmy,
    tmy_hour_of_day,
)
from projects.ev_hosting_flex.scripts._powerflow import (
    annual_performance_metrics,
    flexible_share,
)
from projects.ev_hosting_flex.scripts.config import (
    CLIMATE_BIN_EDGES,
    DTYPE,
    LOAD_GROWTH_GRID,
    PERFORMANCE_REF_EV_PER_HOME,
    POOL_TILES,
    POWER_FACTOR,
    ROUND_DECIMALS,
    TRANSFORMER_KVA,
)
from projects.ev_hosting_flex.scripts.pipeline.analyze_flexibility_incentive import (
    _policy_ceiling_ev_per_home,
)
from projects.ev_hosting_flex.scripts.pipeline.validate_powerflow import (
    size_network_to_load,
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

    if float(growth_grid[0]) != 1.0:
        raise ValueError(
            "growth_grid[0] must be 1.0 — growth_margin_p50 is measured at G=1 "
            f"(the as-built network); got {growth_grid[0]}."
        )
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


def _g_at_ceiling(
    growth_grid: tuple[float, ...], ceilings: list[float], target: float
) -> float:
    """Largest G at which ``ceilings`` (decreasing in G) is still >= target.

    Linear interpolation of the down-crossing; the grid floor if already below
    at the lowest G, the grid ceiling if it never drops below in range.
    """
    gs = [float(x) for x in growth_grid]
    below = [i for i, c in enumerate(ceilings) if c < target]
    if not below:
        return round(gs[-1], ROUND_DECIMALS)
    j = below[0]
    if j == 0:
        return round(gs[0], ROUND_DECIMALS)
    g0, g1, c0, c1 = gs[j - 1], gs[j], ceilings[j - 1], ceilings[j]
    if c0 == c1:
        return round(g1, ROUND_DECIMALS)
    return round(g0 + (target - c0) * (g1 - g0) / (c1 - c0), ROUND_DECIMALS)


def _peak_flexible_share(base_annual_t: np.ndarray, ev_overlay: np.ndarray) -> float:
    """Flexible (EV) share at the transformer's coincident annual peak."""
    total = base_annual_t + ev_overlay
    h = int(np.argmax(total))
    return flexible_share(float(base_annual_t[h]), float(ev_overlay[h]))


def _feeder_window(
    grid: tuple[float, ...],
    base_feeder: np.ndarray,
    pool_ext: np.ndarray,
    cold: dict[str, Any],
    rating_feeder: float,
    hod0: int,
    charger_kw: np.ndarray,
    n_max: int,
) -> dict[str, Any]:
    """Uncontrolled vs optimal-shift hosting ceiling across the growth grid,
    plus the flexibility window (G-range where the target penetration is
    hosted only with shift, not uncontrolled)."""
    unc_ceiling, shift_ceiling = [], []
    for g in grid:
        base_g = base_feeder * g
        unc_ceiling.append(
            _policy_ceiling_ev_per_home(
                base=base_g,
                pool=pool_ext,
                day_indices=cold["day_indices"],
                policy="uncontrolled",
                rating_kw=rating_feeder,
                hod0=hod0,
                charger_kw=charger_kw,
                n_max=n_max,
            )
        )
        shift_ceiling.append(
            _policy_ceiling_ev_per_home(
                base=base_g,
                pool=pool_ext,
                day_indices=cold["day_indices"],
                policy="shift",
                rating_kw=rating_feeder,
                hod0=hod0,
                charger_kw=charger_kw,
                n_max=n_max,
            )
        )
    t_ref = float(PERFORMANCE_REF_EV_PER_HOME)
    g_low = _g_at_ceiling(grid, unc_ceiling, t_ref)
    g_high = _g_at_ceiling(grid, shift_ceiling, t_ref)
    return {
        "growth_grid": [round(float(g), 6) for g in grid],
        "uncontrolled_ceiling": [round(float(x), ROUND_DECIMALS) for x in unc_ceiling],
        "shift_ceiling": [round(float(x), ROUND_DECIMALS) for x in shift_ceiling],
        "flex_window_g_low": g_low,
        "flex_window_g_high": g_high,
    }


def derive_performance(script: ProjectScript) -> dict[str, Any]:
    cache_dir = script.cache_dir
    data_dir = script.data_dir
    """Size the net at G=1, build the panel, the flexible share, and the feeder
    flexibility window; assemble the payload + figure."""
    with open(cache_dir / "pp_net_cache.pkl", "rb") as handle:
        net = pickle.load(handle)
    feeder_idx = int(
        script.read_json("outputs/cache/feeder_selection.json")[
            "feeder_transformer_idx"
        ]
    )
    temp = load_annual_tmy()
    hod0 = int(tmy_hour_of_day(temp))
    from projects.ev_hosting_flex.scripts._annual import day_mean_temps

    design_day = int(np.argmin(day_mean_temps(temp)))
    sizing = size_network_to_load(net, cache_dir, temp, design_day, feeder_idx)
    size_by_trafo = sizing["size_by_trafo"]

    pf = float(POWER_FACTOR)
    lv = net.trafo.index[net.trafo["vn_lv_kv"] < 1.0]
    homes_by_trafo = {int(t): int(size_by_trafo[int(t)]) for t in lv}
    rating_by_trafo = {
        int(t): float(net.trafo.at[int(t), "sn_mva"]) * 1000.0 * pf for t in lv
    }

    base_feeder = aggregate_to_hourly(
        np.load(data_dir / "base_annual.npy").astype(DTYPE)
    )[0]
    per_home = (base_feeder / 6.0).astype(DTYPE)
    pool_h = aggregate_to_hourly(
        np.load(data_dir / "ev_fleet_annual.npy").astype(DTYPE)
    )
    per_ev = pool_h.mean(axis=0).astype(DTYPE)  # mean per-EV annual profile

    grid = tuple(float(g) for g in LOAD_GROWTH_GRID)
    panel = _build_panel(per_home, homes_by_trafo, rating_by_trafo, grid)

    # flexible-vs-inflexible peak decomposition at G=1, reference penetration T
    t_ref = float(PERFORMANCE_REF_EV_PER_HOME)
    shares = []
    for t in homes_by_trafo:
        h = homes_by_trafo[t]
        base_t = per_home * h
        ev_overlay = t_ref * h * per_ev
        shares.append(_peak_flexible_share(base_t, ev_overlay))
    flexible_share_p50 = round(float(np.median(shares)), ROUND_DECIMALS)

    # feeder flexibility window: uncontrolled vs optimal-shift ceiling vs G
    pool_ext = np.tile(pool_h, (int(POOL_TILES), 1)).astype(DTYPE)
    charger_kw = pool_ext.max(axis=1).astype(DTYPE)
    n_max = pool_ext.shape[0]
    cold = min(
        climate_bin_days(temp, CLIMATE_BIN_EDGES), key=lambda b: b["mean_temp_c"]
    )
    rating_feeder = float(TRANSFORMER_KVA) * pf
    feeder_window = _feeder_window(
        grid, base_feeder, pool_ext, cold, rating_feeder, hod0, charger_kw, n_max
    )

    payload = {
        "reference_ev_per_home": t_ref,
        "rating_feeder_kw": round(rating_feeder, ROUND_DECIMALS),
        "panel": panel,
        "flexible_share_p50": flexible_share_p50,
        "feeder_window": feeder_window,
    }
    out_path_ref = script.write_json("outputs/json/network_performance.json", payload)
    fig_paths = _figures(payload, script.figures_dir)

    summary = {
        "n_trafos": panel["n_trafos"],
        "growth_margin_p50": panel["growth_margin_p50"],
        "n_over_100_at_g_high": panel["n_over_100_by_g"][-1],
        "flexible_share_p50": flexible_share_p50,
        "flex_window_g_low": feeder_window["flex_window_g_low"],
        "flex_window_g_high": feeder_window["flex_window_g_high"],
    }
    return {"artifact_paths": [out_path_ref, *fig_paths], "summary": summary}


def _figures(payload: dict[str, Any], figures_dir: Path) -> list[Path]:
    """Three-panel figure: overload curve, flexible share, feeder window."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    panel = payload["panel"]
    gs = panel["growth_grid"]
    fw = payload["feeder_window"]
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(14.5, 4.3))

    ax1.plot(gs, panel["n_over_100_by_g"], "o-", color="C3", label=">100%")
    ax1.plot(gs, panel["n_over_90_by_g"], "s--", color="C1", label=">90%")
    ax1.set_xlabel("load-growth factor G")
    ax1.set_ylabel("transformers over limit")
    ax1.set_title(f"Overload curve (margin p50 {panel['growth_margin_p50']:.1f}%)")
    ax1.legend(fontsize=8)

    ax2.plot(gs, panel["median_peak_util_by_g"], "o-", color="C0", label="median")
    ax2.plot(gs, panel["p95_peak_util_by_g"], "s--", color="C4", label="p95")
    ax2.axhline(100.0, color="k", ls=":", lw=1)
    ax2.set_xlabel("load-growth factor G")
    ax2.set_ylabel("transformer peak utilization (%)")
    ax2.set_title(
        f"Utilization vs load (flex share p50 {payload['flexible_share_p50']:.2f})"
    )
    ax2.legend(fontsize=8)

    ax3.plot(
        fw["growth_grid"],
        fw["uncontrolled_ceiling"],
        "s--",
        color="C0",
        label="uncontrolled",
    )
    ax3.plot(
        fw["growth_grid"], fw["shift_ceiling"], "o-", color="C2", label="optimal shift"
    )
    ax3.axhline(
        payload["reference_ev_per_home"], color="k", ls=":", lw=1, label="target"
    )
    ax3.axvspan(
        fw["flex_window_g_low"], fw["flex_window_g_high"], color="C2", alpha=0.12
    )
    ax3.set_xlabel("load-growth factor G")
    ax3.set_ylabel("feeder hosting ceiling (EV/home)")
    ax3.set_title("Flexibility window (shaded band)")
    ax3.legend(fontsize=8)

    fig.suptitle(
        "Network performance vs load growth: the flexibility window",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    paths = []
    for suffix in (".png", ".pdf"):
        p = figures_dir / f"network_performance{suffix}"
        fig.savefig(p, dpi=200, bbox_inches="tight")
        paths.append(p)
    plt.close(fig)
    return paths


def run_stage() -> dict[str, Any]:
    """Run the network-performance stage and emit the platform report."""
    from gridalyn.projects.scripting import project_script

    script = project_script()
    derived = derive_performance(script)
    warnings = [
        "HOMOGENEOUS-BASE APPROXIMATION: per-transformer annual load is the "
        "governed feeder's per-home profile broadcast to each transformer's home "
        "count (× G). It ignores inter-home diversity beyond the feeder's own — "
        "consistent with the study's per-size modelling; the per-transformer "
        "numbers are indicative, the STRUCTURE (curve vs G, the window band) is "
        "robust.",
        "SCOPE: pure-kW (static rating), no AC. The load-growth factor G scales "
        "the INFLEXIBLE heating base only; EVs are the flexible overlay.",
    ]
    return script.write_report(
        "network_performance_report",
        artifacts=[
            p if isinstance(p, dict) else script.file_reference(p)
            for p in derived["artifact_paths"]
        ],
        summary=derived["summary"],
        validation={"valid": True, "errors": [], "warnings": warnings},
    )


def main() -> None:
    """CLI entry point for the network-performance stage."""
    argparse.ArgumentParser(description=__doc__).parse_args()
    report = run_stage()
    s = report.get("summary", {})
    print(
        "Network performance + report: growth margin p50 "
        f"{s.get('growth_margin_p50')}% | {s.get('n_over_100_at_g_high')}/"
        f"{s.get('n_trafos')} trafos over 100% at max G | flexible share p50 "
        f"{s.get('flexible_share_p50')} | flexibility window G "
        f"[{s.get('flex_window_g_low')}, {s.get('flex_window_g_high')}]"
    )


if __name__ == "__main__":
    main()
