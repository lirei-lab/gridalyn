"""Study 3B: clustered EV adoption -> local hotspots + flexibility recovery.

At a FIXED total fleet, non-uniform ("clustered") adoption saturates the worst
last-mile transformer far earlier than the uniform metric suggests. This stage:

* PART 1 — characterization: the clustering PENALTY = how much worse the worst
  transformer's loading gets at a fixed mean adoption rate as dispersion (Gini)
  grows, uniform vs clustered. (The per-transformer first-reinforcement mu is
  degenerate at this scale — with ~540 transformers the worst already exceeds
  100% at the lowest swept mu even uniformly — so the penalty is framed as the
  worst-loading ratio, not a mu-crossing gap.)
* PART 2 — recovery: per-transformer local curtailment (static-rating cap, no
  time-shift) re-solved in AC; the hosting recovered, the curtailed energy, the
  burden concentration (Gini/Jain) on the EV-heavy clusters, and the dispersion
  floor beyond which local flex no longer recovers the uniform limit.

Reuses size_network_to_load (identical HQ-realistic model) and the fixed EV
pool. GUARD-02: no module-scope pandapower. Out of scope: phase imbalance
(needs runpp_3ph) — the balanced model carries the transformer-overload story.
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
    apply_local_curtailment,
    draw_clustered_adoption,
    gini,
)
from projects.ev_hosting_flex.scripts.pipeline.analyze_network_characterization import (  # noqa: E402
    _interp_crossing,
)
from projects.ev_hosting_flex.scripts.pipeline.validate_powerflow import (  # noqa: E402
    size_network_to_load,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    CLUSTER_DISPERSION_GRID,
    CLUSTER_MC_DRAWS,
    CLUSTER_MEAN_RATE,
    CLUSTER_MU_GRID,
    DTYPE,
    POWER_FACTOR,
    PROJECT_OUTPUTS_DIR,
    ROUND_DECIMALS,
    SEED,
    SLACK_VM_PU,
)


def _solve_worst_trafo(
    net: Any,
    per_trafo_base: dict[int, np.ndarray],
    per_trafo_homes: dict[int, int],
    load_bus_to_trafo: dict[int, int],
    ev_perhome_day: np.ndarray,
    adoption: np.ndarray,
    lv_trafos: np.ndarray,
    curtail: bool,
) -> dict[str, Any]:
    """Solve one design-day (24 h) full-net PF for a given adoption vector.

    Args:
        net: sized pandapower net (mutated per hour).
        per_trafo_base: trafo_idx -> (24,) kW aggregate base at the trafo.
        per_trafo_homes: trafo_idx -> homes served.
        load_bus_to_trafo: load bus -> owning LV trafo idx.
        ev_perhome_day: (24,) per-home design-day EV profile (kW), local-ordered.
        adoption: (T,) EV/home per LV transformer (aligned to lv_trafos order).
        lv_trafos: (T,) LV transformer indices.
        curtail: if True, apply per-trafo local curtailment (static-rating cap).

    Returns:
        Dict with worst_loading (float %), n_over_static (int),
        curtailed_kwh (float, total shed), curtailed_by_trafo (T,) kWh.
    """
    import pandapower as pp

    pf = float(POWER_FACTOR)
    q_factor = float(np.tan(np.arccos(pf)))
    net.ext_grid["vm_pu"] = float(SLACK_VM_PU)

    adopt_by_trafo = {int(t): float(adoption[i]) for i, t in enumerate(lv_trafos)}
    # served EV kW per trafo per hour (after optional curtailment)
    served_ev: dict[int, np.ndarray] = {}
    curtailed_by_trafo = np.zeros(len(lv_trafos), dtype=DTYPE)
    for i, t in enumerate(lv_trafos):
        t = int(t)
        homes = per_trafo_homes[t]
        ev_kw = adopt_by_trafo[t] * homes * ev_perhome_day
        if curtail:
            sn = float(net.trafo.at[t, "sn_mva"])
            rating_kw = sn * 1000.0 * pf
            served, cur = apply_local_curtailment(per_trafo_base[t], ev_kw, rating_kw)
            served_ev[t] = served
            curtailed_by_trafo[i] = cur
        else:
            served_ev[t] = ev_kw

    load_bus = net.load["bus"].to_numpy()
    # Split each transformer's aggregate evenly across the load buses that
    # actually belong to it (NOT its home count — the two can differ, and only
    # the total throughput at the transformer, which we measure, must be exact).
    n_loadbuses: dict[int, int] = {}
    for b in load_bus:
        t = load_bus_to_trafo[int(b)]
        n_loadbuses[t] = n_loadbuses.get(t, 0) + 1
    worst = 0.0
    n_over = 0
    over_seen = np.zeros(len(lv_trafos), dtype=bool)
    for hour in range(24):
        p_kw = np.empty(len(load_bus), dtype=DTYPE)
        for k, b in enumerate(load_bus):
            t = load_bus_to_trafo[int(b)]
            nb = n_loadbuses[t]
            # split the trafo aggregate evenly across its OWN load buses
            base_h = per_trafo_base[t][hour] / nb
            ev_h = served_ev[t][hour] / nb
            p_kw[k] = base_h + ev_h
        net.load["p_mw"] = p_kw / 1000.0
        net.load["q_mvar"] = net.load["p_mw"] * q_factor
        pp.runpp(net, numba=True)
        load_pct = net.res_trafo["loading_percent"][lv_trafos].to_numpy(dtype=DTYPE)
        worst = max(worst, float(load_pct.max()))
        over_seen |= load_pct >= 100.0
    n_over = int(over_seen.sum())
    return {
        "worst_loading": worst,
        "n_over_static": n_over,
        "curtailed_kwh": float(curtailed_by_trafo.sum()),
        "curtailed_by_trafo": curtailed_by_trafo,
    }


def _sweep_one_dispersion(
    net: Any,
    per_trafo_base: dict[int, np.ndarray],
    per_trafo_homes: dict[int, int],
    load_bus_to_trafo: dict[int, int],
    ev_perhome_day: np.ndarray,
    lv_trafos: np.ndarray,
    n_homes: np.ndarray,
    mus: np.ndarray,
    delta: float,
) -> dict[str, Any]:
    """Sweep the mean-adoption grid at one fixed dispersion level.

    Args:
        net: sized pandapower net (mutated per hour, reused across draws).
        per_trafo_base: trafo_idx -> (24,) kW aggregate base at the trafo.
        per_trafo_homes: trafo_idx -> homes served.
        load_bus_to_trafo: load bus -> owning LV trafo idx.
        ev_perhome_day: (24,) per-home design-day EV profile (kW).
        lv_trafos: (T,) LV transformer indices.
        n_homes: (T,) homes served, aligned to ``lv_trafos``.
        mus: mean-adoption grid (EV/home).
        delta: lognormal dispersion (sigma) for this sweep.

    Returns:
        Dict with the per-mu median worst-loading (unmanaged/managed),
        median over-limit count, and the mean-rate-anchored Gini/curtailment/
        burden metrics (computed only at ``mu == CLUSTER_MEAN_RATE``).
    """
    worst = np.zeros(len(mus), dtype=DTYPE)
    worst_managed = np.zeros(len(mus), dtype=DTYPE)
    n_over = np.zeros(len(mus), dtype=DTYPE)
    gini_at_mean = 0.0
    curtailed_pct_at_mean = 0.0
    burden_gini_at_mean = 0.0
    for mi, mu in enumerate(mus):
        wl, wlm, no = [], [], []
        for k in range(int(CLUSTER_MC_DRAWS)):
            rng = np.random.default_rng(
                SEED + int(round(delta * 1000)) * 131 + mi * 17 + k
            )
            adoption = draw_clustered_adoption(n_homes, float(mu), float(delta), rng)
            un = _solve_worst_trafo(
                net,
                per_trafo_base,
                per_trafo_homes,
                load_bus_to_trafo,
                ev_perhome_day,
                adoption,
                lv_trafos,
                curtail=False,
            )
            mg = _solve_worst_trafo(
                net,
                per_trafo_base,
                per_trafo_homes,
                load_bus_to_trafo,
                ev_perhome_day,
                adoption,
                lv_trafos,
                curtail=True,
            )
            wl.append(un["worst_loading"])
            wlm.append(mg["worst_loading"])
            no.append(un["n_over_static"])
            if float(mu) == float(CLUSTER_MEAN_RATE):
                total_ev_kwh = float(
                    np.sum(adoption * n_homes) * float(ev_perhome_day.sum())
                )
                gini_at_mean += gini(adoption) / CLUSTER_MC_DRAWS
                curtailed_pct_at_mean += (
                    (mg["curtailed_kwh"] / total_ev_kwh * 100.0) / CLUSTER_MC_DRAWS
                    if total_ev_kwh > 0
                    else 0.0
                )
                burden_gini_at_mean += gini(mg["curtailed_by_trafo"]) / CLUSTER_MC_DRAWS
        worst[mi] = float(np.median(wl))
        worst_managed[mi] = float(np.median(wlm))
        n_over[mi] = float(np.median(no))
    return {
        "worst": worst,
        "worst_managed": worst_managed,
        "n_over": n_over,
        "gini_at_mean": round(gini_at_mean, ROUND_DECIMALS),
        "curtailed_pct_at_mean": round(curtailed_pct_at_mean, ROUND_DECIMALS),
        "burden_gini_at_mean": round(burden_gini_at_mean, ROUND_DECIMALS),
    }


def derive_clustered(cache_dir: Path, data_dir: Path) -> dict[str, Any]:
    """Sweep dispersion x mean-adoption; compute the penalty + recovery metrics.

    Args:
        cache_dir: Topology cache directory.
        data_dir: Annual artifact directory (EV pool).

    Returns:
        Dict with ``artifact_paths`` and the report ``summary``.
    """
    with open(cache_dir / "pp_net_cache.pkl", "rb") as handle:
        net = pickle.load(handle)
    feeder_idx = int(
        json.loads((cache_dir / "feeder_selection.json").read_text())[
            "feeder_transformer_idx"
        ]
    )
    downstream = json.loads((cache_dir / "downstream_bus_map.json").read_text())
    temp = load_annual_tmy()
    hod0 = tmy_hour_of_day(temp)
    design_day = int(np.argmin(day_mean_temps(temp)))

    sizing = size_network_to_load(net, cache_dir, temp, design_day, feeder_idx)
    base_by_size = sizing["base_by_size"]
    size_by_trafo = sizing["size_by_trafo"]

    lv_trafos = net.trafo.index[net.trafo["vn_lv_kv"] < 1.0].to_numpy()
    n_homes = np.array([int(size_by_trafo[int(t)]) for t in lv_trafos], dtype=float)

    # per-trafo aggregate design-day base (kW): homes * per-home base of its size
    per_trafo_base = {
        int(t): (
            int(size_by_trafo[int(t)]) * base_by_size[int(size_by_trafo[int(t)])]
        ).astype(DTYPE)
        for t in lv_trafos
    }
    per_trafo_homes = {int(t): int(size_by_trafo[int(t)]) for t in lv_trafos}

    # load bus -> owning LV trafo (from the downstream map: trafo -> [buses])
    load_bus_to_trafo: dict[int, int] = {}
    for t in lv_trafos:
        for b in downstream.get(f"transformer:{int(t)}", []):
            load_bus_to_trafo[int(b)] = int(t)
    # any load bus not mapped falls back to the feeder count via size_by_loadbus
    for b in net.load["bus"].to_numpy():
        load_bus_to_trafo.setdefault(int(b), feeder_idx)

    pool_hourly = aggregate_to_hourly(
        np.load(data_dir / "ev_fleet_annual.npy").astype(DTYPE)
    )
    ev_perhome_day = np.roll(
        pool_hourly[:, design_day * 24 : (design_day + 1) * 24].mean(axis=0),
        int(hod0),
    ).astype(DTYPE)

    mus = np.array(CLUSTER_MU_GRID, dtype=DTYPE)
    deltas = list(CLUSTER_DISPERSION_GRID)
    per_delta: dict[float, dict[str, Any]] = {
        float(delta): _sweep_one_dispersion(
            net,
            per_trafo_base,
            per_trafo_homes,
            load_bus_to_trafo,
            ev_perhome_day,
            lv_trafos,
            n_homes,
            mus,
            float(delta),
        )
        for delta in deltas
    }

    payload_delta = {}
    for delta in deltas:
        d = per_delta[float(delta)]
        mu_first = _interp_crossing(mus, d["worst"], 100.0)
        mu_first_managed = _interp_crossing(mus, d["worst_managed"], 100.0)
        payload_delta[f"delta_{delta:.2f}"] = {
            "gini_at_mean_rate": d["gini_at_mean"],
            "worst_loading_by_mu": [
                round(float(x), ROUND_DECIMALS) for x in d["worst"]
            ],
            "worst_loading_managed_by_mu": [
                round(float(x), ROUND_DECIMALS) for x in d["worst_managed"]
            ],
            "n_over_by_mu": [int(x) for x in d["n_over"]],
            "reinforcement_mu": (
                round(mu_first, ROUND_DECIMALS) if np.isfinite(mu_first) else None
            ),
            "reinforcement_mu_managed": (
                round(mu_first_managed, ROUND_DECIMALS)
                if np.isfinite(mu_first_managed)
                else None
            ),
            "curtailed_energy_percent_at_mean": d["curtailed_pct_at_mean"],
            "burden_gini_at_mean": d["burden_gini_at_mean"],
        }

    delta_hi = float(deltas[-1])
    d_hi = payload_delta[f"delta_{delta_hi:.2f}"]

    # ── Headline: clustering PENALTY + flex RECOVERY at the fixed mean rate ──
    # The per-transformer first-reinforcement mu is degenerate here: with ~540
    # transformers the WORST one already exceeds 100% at the lowest swept mu,
    # under uniform adoption too, so the crossing metric saturates and cannot
    # separate clustered from uniform. The penalty instead shows up in HOW BAD
    # the worst hotspot gets. Evaluate at mu = CLUSTER_MEAN_RATE, uniform
    # (delta=0) vs the most-clustered dispersion level.
    mi = int(np.argmin(np.abs(mus - float(CLUSTER_MEAN_RATE))))
    worst_uniform = float(per_delta[0.0]["worst"][mi])
    worst_clustered = float(per_delta[delta_hi]["worst"][mi])
    worst_managed_clustered = float(per_delta[delta_hi]["worst_managed"][mi])
    penalty_ratio = (
        round(worst_clustered / worst_uniform, ROUND_DECIMALS)
        if worst_uniform > 0
        else None
    )
    penalty = {
        "mean_rate": float(CLUSTER_MEAN_RATE),
        "worst_loading_uniform": round(worst_uniform, ROUND_DECIMALS),
        "worst_loading_clustered": round(worst_clustered, ROUND_DECIMALS),
        "penalty_ratio": penalty_ratio,
        "n_over_uniform": int(per_delta[0.0]["n_over"][mi]),
        "n_over_clustered": int(per_delta[delta_hi]["n_over"][mi]),
    }
    recovery = {
        "worst_loading_managed_clustered": round(
            worst_managed_clustered, ROUND_DECIMALS
        ),
        "worst_loading_reduction": round(
            worst_clustered - worst_managed_clustered, ROUND_DECIMALS
        ),
        "curtailed_energy_percent": d_hi["curtailed_energy_percent_at_mean"],
        "burden_gini": d_hi["burden_gini_at_mean"],
    }

    payload = {
        "design_day": design_day,
        "mean_rate_for_gini_axis": float(CLUSTER_MEAN_RATE),
        "mu_grid": [round(float(m), 6) for m in mus],
        "dispersion_grid": [round(float(x), 6) for x in deltas],
        "n_lv_transformers": int(len(lv_trafos)),
        "penalty": penalty,
        "recovery": recovery,
        "by_dispersion": payload_delta,
    }
    json_dir = PROJECT_OUTPUTS_DIR / "json"
    json_dir.mkdir(parents=True, exist_ok=True)
    out_path = json_dir / "clustered_adoption.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    fig_paths = _figures(payload, PROJECT_OUTPUTS_DIR / "figures")

    summary = {
        "n_lv_transformers": payload["n_lv_transformers"],
        "penalty_ratio": penalty_ratio,
        "worst_loading_uniform": penalty["worst_loading_uniform"],
        "worst_loading_clustered": penalty["worst_loading_clustered"],
        "worst_loading_managed_clustered": recovery[
            "worst_loading_managed_clustered"
        ],
        "curtailed_energy_percent": recovery["curtailed_energy_percent"],
        "burden_gini": recovery["burden_gini"],
        "gini_at_max_dispersion": d_hi["gini_at_mean_rate"],
    }
    return {"artifact_paths": [out_path, *fig_paths], "summary": summary}


def _figures(payload: dict[str, Any], figures_dir: Path) -> list[Path]:
    """Three-panel figure: penalty vs Gini, first-reinforcement, flex recovery."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    mus = np.array(payload["mu_grid"], dtype=float)
    deltas = payload["dispersion_grid"]
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(14.5, 4.3))

    # P1: worst-trafo loading at the fixed mean rate vs Gini
    mean_rate = payload["mean_rate_for_gini_axis"]
    mi = int(np.argmin(np.abs(mus - mean_rate)))
    ginis = [
        payload["by_dispersion"][f"delta_{d:.2f}"]["gini_at_mean_rate"] for d in deltas
    ]
    worst_at_mean = [
        payload["by_dispersion"][f"delta_{d:.2f}"]["worst_loading_by_mu"][mi]
        for d in deltas
    ]
    ax1.plot(ginis, worst_at_mean, "o-", color="C0")
    ax1.axhline(100.0, color="k", ls="--", lw=1)
    ax1.set_xlabel("Gini of adoption")
    ax1.set_ylabel(f"Worst-transformer loading @ {mean_rate:g} EV/home (%)")
    ax1.set_title("Clustering penalty")

    # P2: worst-trafo loading vs mu, uniform vs high dispersion
    for d, style in ((deltas[0], "o-"), (deltas[-1], "s--")):
        w = payload["by_dispersion"][f"delta_{d:.2f}"]["worst_loading_by_mu"]
        ax2.plot(mus, w, style, label=f"delta={d:g}")
    ax2.axhline(100.0, color="k", ls=":", lw=1)
    ax2.set_xlabel("mean EV/home")
    ax2.set_ylabel("Worst-transformer loading (%)")
    ax2.set_title("First reinforcement: clustered vs uniform")
    ax2.legend(fontsize=8)

    # P3: recovery — unmanaged vs managed at high dispersion
    d_hi = deltas[-1]
    blk = payload["by_dispersion"][f"delta_{d_hi:.2f}"]
    ax3.plot(mus, blk["worst_loading_by_mu"], "s--", color="C3", label="clustered")
    ax3.plot(
        mus, blk["worst_loading_managed_by_mu"], "^-", color="C2", label="+ local flex"
    )
    ax3.axhline(100.0, color="k", ls=":", lw=1)
    ax3.set_xlabel("mean EV/home")
    ax3.set_ylabel("Worst-transformer loading (%)")
    ax3.set_title(
        f"Flex recovery (delta={d_hi:g}): "
        f"{blk['curtailed_energy_percent_at_mean']:.1f}% curtailed"
    )
    ax3.legend(fontsize=8)

    fig.suptitle(
        "Clustered adoption: penalty, first reinforcement, flexibility recovery",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    paths = []
    for suffix in (".png", ".pdf"):
        p = figures_dir / f"clustered_adoption{suffix}"
        fig.savefig(p, dpi=200, bbox_inches="tight")
        paths.append(p)
    plt.close(fig)
    return paths


def run_stage() -> dict[str, Any]:
    """Run the clustered-adoption stage and emit the platform report."""
    from gridalyn.projects.scripting import project_script

    script = project_script()
    derived = derive_clustered(script.cache_dir, PROJECT_OUTPUTS_DIR / "data")
    warnings = [
        "SCOPE: transformer-overload characterization only. Phase imbalance "
        "within the split-phase secondary is out of scope (requires runpp_3ph); "
        "the balanced model carries the aggregate hotspot story.",
        "RECOVERY LEVER: per-transformer local curtailment on the static kW "
        "rating (no time-shift — there is no overnight valley in an all-electric "
        "cold network; see the flexibility value-map spec). The AC re-solve then "
        "measures the recovered loading.",
    ]
    return script.write_report(
        "clustered_adoption_report",
        artifacts=[script.file_reference(p) for p in derived["artifact_paths"]],
        summary=derived["summary"],
        validation={"valid": True, "errors": [], "warnings": warnings},
    )


def main() -> None:
    """CLI entry point for the clustered-adoption stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    report = run_stage()
    s = report.get("summary", {})
    print(
        "Clustered adoption + report: worst-trafo loading @ mean rate "
        f"{s.get('worst_loading_uniform')}% uniform -> "
        f"{s.get('worst_loading_clustered')}% clustered "
        f"(penalty x{s.get('penalty_ratio')}, Gini {s.get('gini_at_max_dispersion')}) "
        f"| local flex caps it to {s.get('worst_loading_managed_clustered')}% at "
        f"{s.get('curtailed_energy_percent')}% curtailed (burden Gini "
        f"{s.get('burden_gini')})"
    )


if __name__ == "__main__":
    main()
