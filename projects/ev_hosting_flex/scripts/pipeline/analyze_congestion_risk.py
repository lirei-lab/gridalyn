"""Probabilistic congestion-risk DIAGNOSTIC (diagnosis before solutions).

Monte-Carlos both stochastic generators — the SDK building base
(``annual_base_realization``, per distinct transformer size, cached) and the EV
fleet (``ev_fleet_annual``) — crosses them on cold days, and takes the 15-min
coincident daily-max peak, to estimate the PROBABILITY and PEAK-SEVERITY of
congestion across a realistic load-growth surface (G × EV/home). Peaks, not
averages; cold-conditioned. No flexibility. Pure-kW; transformers of equal
home-count are statistically identical, so stats are computed per distinct size
and mapped to the 540. Out of scope: flexibility, AC voltage, phase imbalance.
"""

from __future__ import annotations

import argparse
import math
import pickle
from pathlib import Path
from typing import Any

import numpy as np

from gridalyn.projects.scripting import ProjectScript
from projects.ev_hosting_flex.scripts._annual import (
    annual_base_realization,
    cold_capability_curve,
    day_mean_temps,
    ev_fleet_annual,
    feeder_rating,
    load_annual_tmy,
    tmy_hour_of_day,
)
from projects.ev_hosting_flex.scripts._powerflow import (
    _cold_day_peaks,
    congestion_stats,
)
from projects.ev_hosting_flex.scripts.config import (
    ANNUAL_RES_MINUTES,
    COLD_DAY_TMEAN_C,
    CONGESTION_AT_RISK_FRACTION,
    CONGESTION_EV_PER_HOME_GRID,
    CONGESTION_G_GRID,
    CONGESTION_K_BASE,
    CONGESTION_K_EV,
    CONGESTION_RISK_THRESHOLD,
    DTYPE,
    POWER_FACTOR,
    ROUND_DECIMALS,
    SEED,
)
from projects.ev_hosting_flex.scripts.pipeline.validate_powerflow import (
    size_network_to_load,
)

_STEPS_PER_DAY = 24 * (60 // int(ANNUAL_RES_MINUTES))


def _base_mc_signature(k_base: int) -> str:
    """Signature of the base-determining config, so the cache invalidates on a
    base recalibration (R/DHW/BG_SCALE re-base) instead of silently reusing a
    stale MC (the 2026-07-14 DHW re-base footgun)."""
    import hashlib

    from projects.ev_hosting_flex.scripts import config as _cfg

    parts = (
        _cfg.R_STUDY_B,
        _cfg.P_HEAT_QUEBEC,
        _cfg.BG_SCALE,
        _cfg.DHW_ELEMENT_KW,
        _cfg.DHW_DAILY_L_MEAN,
        _cfg.DHW_DAILY_L_STD,
        _cfg.DHW_TANK_L,
        _cfg.DHW_T_SET,
        _cfg.DHW_T_LOW,
        _cfg.DHW_UA_KW_PER_K,
        _cfg.DHW_SEED_SALT,
        int(SEED),
        int(ANNUAL_RES_MINUTES),
        int(k_base),
    )
    return hashlib.sha256(repr(parts).encode()).hexdigest()[:16]


def _ensure_base_mc_cache(
    data_dir: Path, temp: Any, sizes: list[int], k_base: int
) -> dict[int, np.ndarray]:
    """K base realizations per distinct home-count, cached in an npz.

    Returns ``{home_count: (k_base, n_steps) kW}``. Deterministic (seeds derived
    from SEED); regenerates if the cache is absent OR its base-config signature
    no longer matches (so a base recalibration is never silently reused).
    """
    path = data_dir / "base_mc_by_size.npz"
    sig = _base_mc_signature(k_base)
    if path.is_file():
        z = np.load(path)
        cached_sig = str(z["_sig"]) if "_sig" in z.files else ""
        if cached_sig == sig:
            return {int(k): z[k].astype(DTYPE) for k in z.files if k != "_sig"}
    out: dict[int, np.ndarray] = {}
    for h in sorted(sizes):
        out[h] = np.stack(
            [
                annual_base_realization(temp, int(h), SEED + 100003 + int(h) * 211 + k)
                for k in range(int(k_base))
            ]
        ).astype(DTYPE)
    np.savez(path, _sig=np.array(sig), **{str(h): out[h] for h in out})
    return out


def _ev_pools(n_max: int, tday: np.ndarray, hod0: int, k_ev: int) -> list[np.ndarray]:
    """K EV-fleet draws of ``n_max`` EVs each; per-scenario counts use prefixes."""
    return [
        ev_fleet_annual(
            np.random.default_rng(SEED + 500003 + k), int(n_max), tday, int(hod0)
        ).astype(DTYPE)
        for k in range(int(k_ev))
    ]


def _size_congestion(
    base_mc: np.ndarray,
    ev_pools: list[np.ndarray],
    cold_mask: np.ndarray,
    steps_per_day: int,
    *,
    homes: int,
    rating_kw: float,
    g: float,
    ev_per_home: float,
    k_curve: np.ndarray | None = None,
) -> dict[str, float]:
    """Congestion stats for one (size, G, ev/home) — base×EV×cold-day peaks."""
    n_evs = int(round(float(ev_per_home) * int(homes)))
    # A cold-day peak is judged against the capability that day's ambient
    # allows (RATING_CONVENTION): load and capability rise together here.
    limit = rating_kw if k_curve is None else rating_kw * k_curve
    peaks: list[np.ndarray] = []
    for kb in range(base_mc.shape[0]):
        base_g = base_mc[kb] * float(g)
        if n_evs <= 0:
            peaks.append(_cold_day_peaks(base_g / limit, cold_mask, steps_per_day))
            continue
        for pool in ev_pools:
            total = base_g + pool[:n_evs].sum(axis=0)
            # Divide BEFORE the daily max: with a moving limit the peak-load
            # step is not the peak-loading step.
            peaks.append(_cold_day_peaks(total / limit, cold_mask, steps_per_day))
    return congestion_stats(np.concatenate(peaks), 1.0)


def derive_congestion(script: ProjectScript) -> dict[str, Any]:
    cache_dir = script.cache_dir
    data_dir = script.data_dir
    """Size at G=1, MC both generators per size, assemble the risk surface."""
    with open(cache_dir / "pp_net_cache.pkl", "rb") as handle:
        net = pickle.load(handle)
    feeder_idx = int(
        script.read_json("outputs/cache/feeder_selection.json")[
            "feeder_transformer_idx"
        ]
    )
    temp = load_annual_tmy()
    hod0 = int(tmy_hour_of_day(temp))
    tday = day_mean_temps(temp)
    cold_mask = tday < float(COLD_DAY_TMEAN_C)
    design_day = int(np.argmin(tday))
    sizing = size_network_to_load(net, cache_dir, temp, design_day, feeder_idx)
    size_by_trafo = sizing["size_by_trafo"]

    pf = float(POWER_FACTOR)
    lv = net.trafo.index[net.trafo["vn_lv_kv"] < 1.0]
    homes_by_trafo = {int(t): int(size_by_trafo[int(t)]) for t in lv}
    rating_by_trafo = {
        int(t): float(net.trafo.at[int(t), "sn_mva"]) * 1000.0 * pf for t in lv
    }
    feeder_homes = homes_by_trafo[feeder_idx]
    sizes = sorted(set(homes_by_trafo.values()))
    rating_by_size = {}
    for h in sizes:
        group = {rating_by_trafo[t] for t in homes_by_trafo if homes_by_trafo[t] == h}
        if len(group) != 1:
            raise ValueError(
                f"transformers with {h} homes have non-uniform ratings {group}; "
                "the per-size congestion mapping assumes one rating per size."
            )
        rating_by_size[h] = group.pop()

    _cap, _series = feeder_rating(temp)
    k_curve = (
        None
        if _series is None
        else cold_capability_curve(temp, res_minutes=int(ANNUAL_RES_MINUTES))
    )
    base_mc = _ensure_base_mc_cache(data_dir, temp, sizes, int(CONGESTION_K_BASE))
    ev_grid = [float(e) for e in CONGESTION_EV_PER_HOME_GRID]
    g_grid = [float(g) for g in CONGESTION_G_GRID]
    n_max = int(math.ceil(max(ev_grid) * max(sizes)))
    ev_pools = _ev_pools(n_max, tday, hod0, int(CONGESTION_K_EV))

    # per (size, G, ev/home) congestion stats
    size_stats: dict[int, dict[str, list[list[dict[str, float]]]]] = {}
    for h in sizes:
        grid = []
        for g in g_grid:
            row = []
            for e in ev_grid:
                row.append(
                    _size_congestion(
                        base_mc[h],
                        ev_pools,
                        cold_mask,
                        _STEPS_PER_DAY,
                        homes=h,
                        rating_kw=rating_by_size[h],
                        g=g,
                        ev_per_home=e,
                        k_curve=k_curve,
                    )
                )
            grid.append(row)
        size_stats[h] = grid

    # network aggregates: fraction/count of the 540 transformers at risk per scenario
    trafo_sizes = [homes_by_trafo[t] for t in homes_by_trafo]
    thr = float(CONGESTION_RISK_THRESHOLD)
    n_at_risk, pcong_p50, pcong_p95 = _network_aggregates(
        size_stats, trafo_sizes, g_grid, ev_grid, thr
    )

    n_trafos = len(trafo_sizes)
    at_risk_frac = [
        [n_at_risk[gi][ei] / n_trafos for ei in range(len(ev_grid))]
        for gi in range(len(g_grid))
    ]
    # First-risk triggers — the diagnostic has TWO independent load-growth axes,
    # so we report both: (a) EV adoption at fixed G=1, and (b) baseline
    # electrification growth G at fixed 0 EV. Either alone can trip the planning
    # threshold; reporting only one would understate the risk.
    g1 = g_grid.index(1.0) if 1.0 in g_grid else 0
    ev0 = ev_grid.index(0.0) if 0.0 in ev_grid else 0
    at_risk_frac_thr = float(CONGESTION_AT_RISK_FRACTION)
    first_risk = _interp_first_cross(ev_grid, at_risk_frac[g1], at_risk_frac_thr)
    first_risk_g = _interp_first_cross(
        g_grid, [at_risk_frac[gi][ev0] for gi in range(len(g_grid))], at_risk_frac_thr
    )

    ref = (
        size_stats[feeder_homes][g1][ev_grid.index(1.0)]
        if 1.0 in ev_grid
        else size_stats[feeder_homes][g1][0]
    )
    ref_ei = ev_grid.index(1.0) if 1.0 in ev_grid else 0

    payload = {
        "n_trafos": n_trafos,
        "feeder_homes": feeder_homes,
        "g_grid": [round(g, 6) for g in g_grid],
        "ev_per_home_grid": [round(e, 6) for e in ev_grid],
        "k_base": int(CONGESTION_K_BASE),
        "k_ev": int(CONGESTION_K_EV),
        "risk_threshold": thr,
        "cold_days": int(np.count_nonzero(cold_mask)),
        "reference_feeder": {
            "homes": feeder_homes,
            "p_cong_g1_1ev": round(ref["p_cong"], ROUND_DECIMALS),
            "peak_max_g1_1ev": round(ref["peak_max"], ROUND_DECIMALS),
            "peak_p99_g1_1ev": round(ref["peak_p99"], ROUND_DECIMALS),
        },
        "n_at_risk_by_scenario": n_at_risk,
        "at_risk_fraction_by_scenario": [
            [round(x, ROUND_DECIMALS) for x in row] for row in at_risk_frac
        ],
        "pcong_p50_by_scenario": pcong_p50,
        "pcong_p95_by_scenario": pcong_p95,
        "n_at_risk_at_ref": int(n_at_risk[g1][ref_ei]),
        "first_risk_ev_per_home": first_risk,
        "first_risk_g": first_risk_g,
        "by_size": {
            str(h): {
                "rating_kw": round(rating_by_size[h], ROUND_DECIMALS),
                "n_trafos": int(trafo_sizes.count(h)),
                "p_cong": [
                    [
                        round(size_stats[h][gi][ei]["p_cong"], ROUND_DECIMALS)
                        for ei in range(len(ev_grid))
                    ]
                    for gi in range(len(g_grid))
                ],
                "peak_max": [
                    [
                        round(size_stats[h][gi][ei]["peak_max"], ROUND_DECIMALS)
                        for ei in range(len(ev_grid))
                    ]
                    for gi in range(len(g_grid))
                ],
            }
            for h in sizes
        },
    }
    out_path_ref = script.write_json("outputs/json/congestion_risk.json", payload)
    fig_paths = _figures(payload, script.figures_dir)

    summary = {
        "n_trafos": n_trafos,
        "cold_days": payload["cold_days"],
        "p_cong_g1_1ev": payload["reference_feeder"]["p_cong_g1_1ev"],
        "peak_max_g1_1ev": payload["reference_feeder"]["peak_max_g1_1ev"],
        "n_at_risk_at_ref": payload["n_at_risk_at_ref"],
        "first_risk_ev_per_home": first_risk,
        "first_risk_g": first_risk_g,
    }
    npz_path = data_dir / "base_mc_by_size.npz"
    artifacts = [out_path_ref, *fig_paths]
    if npz_path.is_file():
        artifacts.append(npz_path)
    return {"artifact_paths": artifacts, "summary": summary}


def _network_aggregates(
    size_stats: dict[int, list[list[dict[str, float]]]],
    trafo_sizes: list[int],
    g_grid: list[float],
    ev_grid: list[float],
    thr: float,
) -> tuple[list[list[int]], list[list[float]], list[list[float]]]:
    """Per-scenario (G x ev/home) at-risk count and P(cong) percentiles."""
    n_at_risk = [[0] * len(ev_grid) for _ in g_grid]
    pcong_p50 = [[0.0] * len(ev_grid) for _ in g_grid]
    pcong_p95 = [[0.0] * len(ev_grid) for _ in g_grid]
    for gi in range(len(g_grid)):
        for ei in range(len(ev_grid)):
            pcs = np.array([size_stats[h][gi][ei]["p_cong"] for h in trafo_sizes])
            n_at_risk[gi][ei] = int(np.count_nonzero(pcs > thr))
            pcong_p50[gi][ei] = round(float(np.percentile(pcs, 50)), ROUND_DECIMALS)
            pcong_p95[gi][ei] = round(float(np.percentile(pcs, 95)), ROUND_DECIMALS)
    return n_at_risk, pcong_p50, pcong_p95


def _interp_first_cross(
    xs: list[float], ys: list[float], target: float
) -> float | None:
    """Smallest x where (increasing) ys first crosses target; interpolated."""
    for i in range(1, len(xs)):
        # the guard forces ys[i-1] < ys[i], so the denominator is never zero
        if ys[i - 1] < target <= ys[i]:
            return round(
                xs[i - 1]
                + (target - ys[i - 1]) * (xs[i] - xs[i - 1]) / (ys[i] - ys[i - 1]),
                ROUND_DECIMALS,
            )
    if ys and ys[0] >= target:
        return round(xs[0], ROUND_DECIMALS)
    return None


def _figures(payload: dict[str, Any], figures_dir: Path) -> list[Path]:
    """Three-panel figure: P(cong) heatmap, peak tail vs adoption, n_at_risk."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    gs = payload["g_grid"]
    evs = payload["ev_per_home_grid"]
    feeder = str(payload["feeder_homes"])
    pcong = np.array(payload["by_size"][feeder]["p_cong"])  # (G, ev)
    peakmax = np.array(payload["by_size"][feeder]["peak_max"])
    n_at_risk = np.array(payload["n_at_risk_by_scenario"])
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(14.5, 4.3))

    im = ax1.imshow(
        pcong, origin="lower", aspect="auto", cmap="Reds", vmin=0.0, vmax=1.0
    )
    ax1.set_xticks(range(len(evs)))
    ax1.set_xticklabels([f"{e:g}" for e in evs])
    ax1.set_yticks(range(len(gs)))
    ax1.set_yticklabels([f"{g:g}" for g in gs])
    ax1.set_xlabel("EV/home")
    ax1.set_ylabel("load growth G")
    ax1.set_title(f"P(congestion) — reference feeder ({feeder} homes)")
    fig.colorbar(im, ax=ax1, fraction=0.046)

    for gi, g in enumerate(gs):
        ax2.plot(evs, peakmax[gi], "o-", label=f"G={g:g}")
    ax2.axhline(100.0, color="k", ls=":", lw=1)
    ax2.set_xlabel("EV/home")
    ax2.set_ylabel("worst cold-day peak (% rating)")
    ax2.set_title("Peak severity (tail max) vs adoption")
    ax2.legend(fontsize=8)

    for gi, g in enumerate(gs):
        ax3.plot(evs, n_at_risk[gi], "o-", label=f"G={g:g}")
    ax3.set_xlabel("EV/home")
    ax3.set_ylabel(f"transformers at risk (P(cong)>{payload['risk_threshold']:g})")
    ax3.set_title(f"At-risk transformers / {payload['n_trafos']}")
    ax3.legend(fontsize=8)

    fig.suptitle(
        "Congestion-risk diagnostic: probability + peak severity vs load growth",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    paths = []
    for suffix in (".png", ".pdf"):
        p = figures_dir / f"congestion_risk{suffix}"
        fig.savefig(p, dpi=200, bbox_inches="tight")
        paths.append(p)
    plt.close(fig)
    return paths


def run_stage() -> dict[str, Any]:
    """Run the congestion-risk diagnostic and emit the platform report."""
    from gridalyn.projects.scripting import project_script

    script = project_script()
    derived = derive_congestion(script)
    warnings = [
        "DIAGNOSTIC ONLY — no flexibility. Characterizes the congestion problem "
        "(probability + peak severity) to inform reinforcement decisions.",
        "PER-SIZE MC: the building base is Monte-Carlo'd per DISTINCT transformer "
        "size (transformers of equal home-count share the realization family); "
        "kW-proxy (power/thermal), no AC voltage or phase imbalance (future "
        "layers). Finite K_BASE/K_EV -> the probabilities carry MC sampling error.",
        "TWO GROWTH AXES: the diagnostic reports both first-risk triggers — EV "
        "adoption at fixed G=1 (first_risk_ev_per_home) AND baseline "
        "electrification growth at zero EV (first_risk_g). Either alone can trip "
        "the planning threshold; do not read the EV trigger as the only driver.",
    ]
    return script.write_report(
        "congestion_risk_report",
        artifacts=[
            p if isinstance(p, dict) else script.file_reference(p)
            for p in derived["artifact_paths"]
        ],
        summary=derived["summary"],
        validation={"valid": True, "errors": [], "warnings": warnings},
    )


def main() -> None:
    """CLI entry point for the congestion-risk diagnostic stage."""
    argparse.ArgumentParser(description=__doc__).parse_args()
    report = run_stage()
    s = report.get("summary", {})
    print(
        "Congestion-risk diagnostic + report: reference feeder P(cong) "
        f"{s.get('p_cong_g1_1ev')} at G=1/1EV/home (peak max "
        f"{s.get('peak_max_g1_1ev')}%) | {s.get('n_at_risk_at_ref')}/"
        f"{s.get('n_trafos')} trafos at risk | first-risk adoption "
        f"{s.get('first_risk_ev_per_home')} EV/home | {s.get('cold_days')} cold days"
    )


if __name__ == "__main__":
    main()
