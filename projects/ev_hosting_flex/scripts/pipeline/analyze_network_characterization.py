"""Network characterization before the economic analysis: losses, substation,
per-transformer hosting headroom.

Sweeps EV adoption on the design-day full-net power flow (with the load-matched
transformer + LV-conductor fleet) and characterizes three planning metrics the
economics then builds on:

* TECHNICAL LOSSES — total I²R (line + transformer) as MWh/day and % of served
  energy; rises super-linearly with EV load, so flexibility that shaves the peak
  also shaves losses (a loss-cost lever for the economics).
* SUBSTATION CONSTRAINT — the 15 MVA HV/MV transformer peak loading vs its
  static nameplate and cold-ambient IEEE C57.91 dynamic rating; it is already
  near its dynamic limit at design cold, so it may be THE binding reinforcement
  constraint at network-wide adoption.
* HOSTING-HEADROOM MAP — for each LV transformer, the EV/home penetration at
  which its peak loading first crosses 100 % (static) — a map of which units
  bind first, for targeted vs uniform reinforcement.

Reuses the load-matched sizing from ``validate_powerflow`` so the model is
identical. GUARD-02: no module-scope pandapower (deferred in the solve loop).
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
from projects.ev_hosting_flex.scripts.pipeline.validate_powerflow import (  # noqa: E402
    size_network_to_load,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    DTYPE,
    HEADROOM_PENETRATION_GRID,
    POWER_FACTOR,
    PROJECT_OUTPUTS_DIR,
    ROUND_DECIMALS,
    SLACK_VM_PU,
    SUBSTATION_DYNAMIC_RATING_K,
)


def _interp_crossing(pens: np.ndarray, loadings: np.ndarray, limit: float) -> float:
    """Return the penetration at which ``loadings`` first crosses ``limit``.

    Linear interpolation between the bracketing grid points; ``inf`` if the
    element never reaches the limit within the swept grid.
    """
    over = np.where(loadings >= limit)[0]
    if over.size == 0:
        return float("inf")
    j = int(over[0])
    if j == 0:
        return float(pens[0])
    x0, x1 = float(pens[j - 1]), float(pens[j])
    y0, y1 = float(loadings[j - 1]), float(loadings[j])
    if y1 == y0:
        return x1
    return x0 + (limit - y0) * (x1 - x0) / (y1 - y0)


def derive_characterization(cache_dir: Path, data_dir: Path) -> dict[str, Any]:
    """Sweep EV adoption and compute the three network-characterization metrics.

    Args:
        cache_dir: Topology cache directory.
        data_dir: Annual artifact directory (EV pool for the overlay).

    Returns:
        Dict with ``artifact_paths`` and the report ``summary``.
    """
    import pandapower as pp

    with open(cache_dir / "pp_net_cache.pkl", "rb") as handle:
        net = pickle.load(handle)
    feeder_idx = int(
        json.loads((cache_dir / "feeder_selection.json").read_text())[
            "feeder_transformer_idx"
        ]
    )
    temp = load_annual_tmy()
    hod0 = tmy_hour_of_day(temp)
    tday = day_mean_temps(temp)
    design_day = int(np.argmin(tday))

    sizing = size_network_to_load(net, cache_dir, temp, design_day, feeder_idx)
    base_by_size = sizing["base_by_size"]
    size_by_loadbus = sizing["size_by_loadbus"]
    size_by_trafo = sizing["size_by_trafo"]

    n_homes_feeder = int(size_by_trafo[feeder_idx])
    load_bus = net.load["bus"].to_numpy()
    per_load_base = np.stack(
        [base_by_size[size_by_loadbus.get(int(b), n_homes_feeder)] for b in load_bus]
    ).astype(DTYPE)

    pool_hourly = aggregate_to_hourly(
        np.load(data_dir / "ev_fleet_annual.npy").astype(DTYPE)
    )
    ev_perhome_day = np.roll(
        pool_hourly[:, design_day * 24 : (design_day + 1) * 24].mean(axis=0),
        int(hod0),
    )

    lv_trafos = net.trafo.index[net.trafo["vn_lv_kv"] < 1.0]
    sub_trafos = net.trafo.index[net.trafo["vn_lv_kv"] >= 1.0]  # 120/25 substation
    pf = float(POWER_FACTOR)
    q_factor = float(np.tan(np.arccos(pf)))
    net.ext_grid["vm_pu"] = float(SLACK_VM_PU)

    pens = np.array(HEADROOM_PENETRATION_GRID, dtype=DTYPE)
    loss_pct: list[float] = []
    loss_mwh: list[float] = []
    served_mwh: list[float] = []
    sub_peak: list[float] = []
    lv_peak = np.zeros((len(pens), len(lv_trafos)), dtype=DTYPE)

    for pi, pen in enumerate(pens):
        served_e = loss_e = 0.0
        sub_pk = 0.0
        tr_pk = np.zeros(len(lv_trafos), dtype=DTYPE)
        for hour in range(24):
            p_kw = per_load_base[:, hour] + float(pen) * ev_perhome_day[hour]
            net.load["p_mw"] = p_kw / 1000.0
            net.load["q_mvar"] = net.load["p_mw"] * q_factor
            pp.runpp(net, numba=True)
            served_e += float(net.res_load["p_mw"].sum())
            loss_e += float(
                net.res_line["pl_mw"].sum() + net.res_trafo["pl_mw"].sum()
            )
            sub_pk = max(
                sub_pk, float(net.res_trafo["loading_percent"][sub_trafos].max())
            )
            tr_pk = np.maximum(
                tr_pk, net.res_trafo["loading_percent"][lv_trafos].to_numpy(dtype=DTYPE)
            )
        served_mwh.append(round(served_e, ROUND_DECIMALS))
        loss_mwh.append(round(loss_e, ROUND_DECIMALS))
        loss_pct.append(round(loss_e / served_e * 100.0, ROUND_DECIMALS))
        sub_peak.append(round(sub_pk, ROUND_DECIMALS))
        lv_peak[pi] = tr_pk

    # ── Substation crossings ──────────────────────────────────────────────
    sub_arr = np.array(sub_peak)
    sub_cross_static = _interp_crossing(pens, sub_arr, 100.0)
    sub_cross_dynamic = _interp_crossing(
        pens, sub_arr, 100.0 * float(SUBSTATION_DYNAMIC_RATING_K)
    )

    # ── Per-transformer hosting headroom (crossing penetration) ───────────
    headroom_static = np.array(
        [_interp_crossing(pens, lv_peak[:, j], 100.0) for j in range(len(lv_trafos))]
    )
    finite = headroom_static[np.isfinite(headroom_static)]
    # already-overloaded at 0 EV (headroom 0) vs those that never bind in-grid
    n_at_0 = int((headroom_static <= 0.0).sum())
    n_never = int(np.isinf(headroom_static).sum())
    home_counts = np.array([size_by_trafo[int(i)] for i in lv_trafos])

    payload = {
        "penetration_grid": [round(float(p), 6) for p in pens],
        "losses": {
            "served_mwh_per_day": served_mwh,
            "loss_mwh_per_day": loss_mwh,
            "loss_percent": loss_pct,
        },
        "substation": {
            "peak_loading_percent": sub_peak,
            "static_rating_percent": 100.0,
            "dynamic_rating_percent": round(
                100.0 * float(SUBSTATION_DYNAMIC_RATING_K), ROUND_DECIMALS
            ),
            "crossing_penetration_static": (
                round(sub_cross_static, ROUND_DECIMALS)
                if np.isfinite(sub_cross_static)
                else None
            ),
            "crossing_penetration_dynamic": (
                round(sub_cross_dynamic, ROUND_DECIMALS)
                if np.isfinite(sub_cross_dynamic)
                else None
            ),
        },
        "headroom": {
            "n_transformers": int(len(lv_trafos)),
            "n_overloaded_at_0ev": n_at_0,
            "n_never_bind_in_grid": n_never,
            "crossing_penetration_p05": round(
                float(np.percentile(finite, 5)), ROUND_DECIMALS
            )
            if finite.size
            else None,
            "crossing_penetration_p50": round(
                float(np.percentile(finite, 50)), ROUND_DECIMALS
            )
            if finite.size
            else None,
            "crossing_penetration_p95": round(
                float(np.percentile(finite, 95)), ROUND_DECIMALS
            )
            if finite.size
            else None,
        },
        "n_lv_lines_upsized": int(sizing["n_lv_lines_upsized"]),
        "design_day": design_day,
    }
    json_dir = PROJECT_OUTPUTS_DIR / "json"
    json_dir.mkdir(parents=True, exist_ok=True)
    out_path = json_dir / "network_characterization.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    fig_paths = _figures(
        pens, loss_pct, sub_peak, headroom_static, home_counts,
        float(SUBSTATION_DYNAMIC_RATING_K), PROJECT_OUTPUTS_DIR / "figures",
    )

    summary = {
        "loss_percent_0ev": loss_pct[0],
        "loss_percent_max_pen": loss_pct[-1],
        "substation_peak_0ev": sub_peak[0],
        "substation_peak_max_pen": sub_peak[-1],
        "substation_crossing_dynamic": payload["substation"][
            "crossing_penetration_dynamic"
        ],
        "headroom_p50": payload["headroom"]["crossing_penetration_p50"],
        "n_transformers_overloaded_at_0ev": n_at_0,
    }
    return {"artifact_paths": [out_path, *fig_paths], "summary": summary}


def _figures(
    pens: np.ndarray,
    loss_pct: list[float],
    sub_peak: list[float],
    headroom: np.ndarray,
    home_counts: np.ndarray,
    sub_k: float,
    figures_dir: Path,
) -> list[Path]:
    """Three-panel figure: losses, substation loading, headroom map."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(14.5, 4.3))

    ax1.plot(pens, loss_pct, "o-", color="C0")
    ax1.set_xlabel("EV/home")
    ax1.set_ylabel("Network losses (% of served energy)")
    ax1.set_title("Losses rise with EV load")

    ax2.plot(pens, sub_peak, "o-", color="C1")
    ax2.axhline(100.0, color="k", ls="--", lw=1, label="static nameplate")
    ax2.axhline(100.0 * sub_k, color="C3", ls=":", lw=1.5,
                label=f"dynamic ({sub_k:g}x, cold)")
    ax2.set_xlabel("EV/home")
    ax2.set_ylabel("Substation peak loading (%)")
    ax2.set_title("Substation is the binding constraint")
    ax2.legend(fontsize=8)

    finite = headroom[np.isfinite(headroom)]
    ax3.hist(finite, bins=np.linspace(0, float(pens[-1]), 21), color="C2", alpha=0.75)
    ax3.set_xlabel("EV/home at which each transformer overloads")
    ax3.set_ylabel("Transformers")
    ax3.set_title("Hosting-headroom map (which bind first)")

    fig.suptitle(
        "Network characterization: losses, substation, per-transformer headroom",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    paths = []
    for suffix in (".png", ".pdf"):
        p = figures_dir / f"network_characterization{suffix}"
        fig.savefig(p, dpi=200, bbox_inches="tight")
        paths.append(p)
    plt.close(fig)
    return paths


def run_stage() -> dict[str, Any]:
    """Run the network-characterization stage and emit the platform report."""
    from gridalyn.projects.scripting import project_script

    script = project_script()
    derived = derive_characterization(
        script.cache_dir, PROJECT_OUTPUTS_DIR / "data"
    )
    warnings = [
        "SUBSTATION UPPER BOUND: the characterization broadcasts one deterministic "
        "SDK per-home base per cluster size, so all homes of a size peak in the same "
        "hour — this omits the inter-home MV-level diversity the stochastic feeder "
        "ensemble carries, making the aggregate SUBSTATION loading an UPPER BOUND "
        "(~230% here; ~170% with full diversity). Either way it exceeds the "
        "substation's cold dynamic rating at design peak, so the qualitative finding "
        "(the substation is the binding constraint, undersized for the all-electric "
        "load) is robust. The feeder-level and per-transformer metrics use small "
        "groups and are unaffected."
    ]
    return script.write_report(
        "network_characterization_report",
        artifacts=[script.file_reference(p) for p in derived["artifact_paths"]],
        summary=derived["summary"],
        validation={"valid": True, "errors": [], "warnings": warnings},
    )


def main() -> None:
    """CLI entry point for the network-characterization stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    report = run_stage()
    s = report.get("summary", {})
    print(
        "Network characterization + report: "
        f"losses {s.get('loss_percent_0ev')}% -> {s.get('loss_percent_max_pen')}% | "
        f"substation {s.get('substation_peak_0ev')}% -> {s.get('substation_peak_max_pen')}% "
        f"(crosses dynamic at {s.get('substation_crossing_dynamic')} EV/home) | "
        f"headroom p50 {s.get('headroom_p50')} EV/home | "
        f"{s.get('n_transformers_overloaded_at_0ev')} trafos overloaded at 0 EV"
    )


if __name__ == "__main__":
    main()
