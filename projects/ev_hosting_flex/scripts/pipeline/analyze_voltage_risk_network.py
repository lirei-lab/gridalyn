"""Probabilistic full-net voltage-risk DIAGNOSTIC (LV undervoltage of the network).

The full-network sibling of validate_powerflow: it probabilizes the deterministic
network-wide LV undervoltage (0.916 pu at 1 EV/home). Loads the cached twin,
applies size_network_to_load (the HQ-sized net), then Monte-Carlos the EV fleet
across the cold days and the adoption grid. Each (draw x cold day x level) builds
a per-load kW vector (each home carries the diversified per-home base of ITS
cluster size + a uniform EV overlay), takes the network coincident-peak hour, and
solves ONE full-net AC (lightsim warm), recording the network-wide min LV bus
voltage. P(min V < CSA 0.917) + the low-voltage tail + the first-risk adoption. No
flexibility. Out of scope: phase imbalance (covered), clustered adoption (covered),
the deep-feeder residual held by LTC/regulators.
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
    annual_base_realization,
    day_mean_temps,
    ev_fleet_annual,
    load_annual_tmy,
    tmy_hour_of_day,
)
from projects.ev_hosting_flex.scripts._powerflow import (  # noqa: E402
    network_min_voltage,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    COLD_DAY_TMEAN_C,
    DTYPE,
    PROJECT_OUTPUTS_DIR,
    ROUND_DECIMALS,
    SEED,
    VOLTAGE_EV_GRID,
    VOLTAGE_LIMITS_PU,
    VOLTAGE_NET_EV_POOL,
    VOLTAGE_NET_MC_DRAWS,
    VOLTAGE_RISK_THRESHOLD,
)
from projects.ev_hosting_flex.scripts.pipeline.analyze_voltage_risk import (  # noqa: E402
    _interp_first_cross,
)


def _adoption_network_voltage_stats(
    net: Any,
    per_load_base_annual: np.ndarray,
    evbar_pools: list[np.ndarray],
    cold_days: list[int],
    n_homes_total: int,
    ev_per_home: float,
    csa: float,
) -> dict[str, Any]:
    """Network min-LV-voltage population over (EV draw x cold day) at adoption
    ``ev_per_home``; returns P(undervoltage), the low tail, and the LV bus that
    holds the population minimum (for the where-it-binds diagnostic).

    Each home carries the per-home base of its cluster size (row of
    ``per_load_base_annual``) plus ``ev_per_home`` * the draw's mean single-EV
    profile; the network coincident-peak hour is taken per day, one full-net AC
    solved there.
    """
    lv_buses = net.bus.index[net.bus["vn_kv"] < 1.0]
    minvs: list[float] = []
    worst_v = 2.0
    worst_bus = -1
    for evbar in evbar_pools:
        for d in cold_days:
            sl = slice(d * 24, (d + 1) * 24)
            base_day = per_load_base_annual[:, sl]              # (n_load, 24)
            ev_day = float(ev_per_home) * np.asarray(evbar[sl], dtype=DTYPE)
            total_by_hour = base_day.sum(axis=0) + n_homes_total * ev_day
            h = int(np.argmax(total_by_hour))
            p_load = (base_day[:, h] + ev_day[h]).astype(DTYPE)  # (n_load,)
            mv = network_min_voltage(net, p_load)
            minvs.append(mv)
            if mv < worst_v:
                worst_v = mv
                worst_bus = int(net.res_bus.loc[lv_buses, "vm_pu"].idxmin())
    arr = np.array(minvs, dtype=DTYPE)
    return {
        "p_undervolt": round(float((arr < csa).mean()), ROUND_DECIMALS),
        "min_v_p50": round(float(np.percentile(arr, 50)), ROUND_DECIMALS),
        "min_v_p05": round(float(np.percentile(arr, 5)), ROUND_DECIMALS),
        "min_v_p01": round(float(np.percentile(arr, 1)), ROUND_DECIMALS),
        "min_v_worst": round(float(arr.min()), ROUND_DECIMALS),
        "worst_bus": worst_bus,
    }


def _sweep_network(
    net: Any,
    per_load_base_annual: np.ndarray,
    evbar_pools: list[np.ndarray],
    cold_days: list[int],
    n_homes_total: int,
    ev_grid: list[float],
    csa: float,
) -> dict[str, Any]:
    """Run `_adoption_network_voltage_stats` across the adoption grid; returns
    the five per-EV metric lists plus the per-level worst bus."""
    keys = ("p_undervolt", "min_v_p50", "min_v_p05", "min_v_p01", "min_v_worst")
    out: dict[str, list[Any]] = {k: [] for k in keys}
    out["worst_bus"] = []
    for e in ev_grid:
        s = _adoption_network_voltage_stats(
            net, per_load_base_annual, evbar_pools, cold_days,
            n_homes_total, e, csa,
        )
        for k in keys:
            out[k].append(s[k])
        out["worst_bus"].append(s["worst_bus"])
    return out


from projects.ev_hosting_flex.scripts.pipeline.validate_powerflow import (  # noqa: E402
    size_network_to_load,
)


def derive_voltage_network(cache_dir: Path) -> dict[str, Any]:
    """Size the full net, MC the EV fleet x cold days; per adoption level compute
    the network LV undervoltage probability + voltage tail."""
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
    cold_days = [int(d) for d in np.where(tday < float(COLD_DAY_TMEAN_C))[0]]

    # ── HQ-style sizing (mutates net trafo/lines/substation in place) ──────
    sizing = size_network_to_load(net, cache_dir, temp, design_day, feeder_idx)
    size_by_loadbus = sizing["size_by_loadbus"]

    # ── Per-load base by cluster size (annual, one deterministic realization) ─
    load_bus = net.load["bus"].to_numpy()
    sizes_present = sorted({int(size_by_loadbus[int(b)]) for b in load_bus
                            if int(b) in size_by_loadbus})
    base_perhome: dict[int, np.ndarray] = {
        n: (
            aggregate_to_hourly(
                annual_base_realization(temp, n, SEED)[None, :].astype(DTYPE)
            )[0]
            / float(n)
        ).astype(DTYPE)
        for n in sizes_present
    }
    fallback = max(sizes_present)
    size_of_load = np.array(
        [int(size_by_loadbus.get(int(b), fallback)) for b in load_bus]
    )
    per_load_base_annual = np.stack(
        [base_perhome[s] for s in size_of_load]
    ).astype(DTYPE)                                        # (n_load, 8760)
    n_homes_total = int(len(load_bus))

    # ── Uniform per-home EV overlay shape: draw's mean single-EV profile ──
    evbar_pools = [
        aggregate_to_hourly(
            ev_fleet_annual(
                np.random.default_rng(SEED + 811 * k),
                int(VOLTAGE_NET_EV_POOL), tday, hod0,
            )
        ).mean(axis=0).astype(DTYPE)
        for k in range(int(VOLTAGE_NET_MC_DRAWS))
    ]

    csa = float(VOLTAGE_LIMITS_PU["normal_low"])
    extreme = float(VOLTAGE_LIMITS_PU["extreme_low"])
    ev_grid = [float(e) for e in VOLTAGE_EV_GRID]

    swept = _sweep_network(
        net, per_load_base_annual, evbar_pools, cold_days,
        n_homes_total, ev_grid, csa,
    )
    p_undervolt = swept["p_undervolt"]
    min_v_p05 = swept["min_v_p05"]
    min_v_worst = swept["min_v_worst"]

    ref = ev_grid.index(1.0) if 1.0 in ev_grid else len(ev_grid) - 1
    first_risk = _interp_first_cross(
        ev_grid, p_undervolt, float(VOLTAGE_RISK_THRESHOLD)
    )

    # where-it-binds diagnostic: cluster size of the reference worst bus. Only
    # map from real LV clusters (size_by_trafo > 0); the MV substation
    # transformer's downstream covers every LV bus in its half with size 0 and
    # must not overwrite the unique pole-transformer size of each LV bus.
    down_map = json.loads((cache_dir / "downstream_bus_map.json").read_text())
    size_by_bus: dict[int, int] = {}
    for key, buses in down_map.items():
        if not key.startswith("transformer:"):
            continue
        idx = int(key.split(":")[1])
        n = int(sizing["size_by_trafo"].get(int(idx), 0))
        if n <= 0:
            continue
        for b in buses:
            size_by_bus[int(b)] = n
    ref_bus = int(swept["worst_bus"][ref])
    binding_size = int(size_by_bus.get(ref_bus, 0))

    payload = {
        "n_homes_total": n_homes_total,
        "ev_per_home_grid": [round(e, 6) for e in ev_grid],
        "mc_draws": int(VOLTAGE_NET_MC_DRAWS),
        "ev_pool": int(VOLTAGE_NET_EV_POOL),
        "n_cold_days": len(cold_days),
        "design_day": design_day,
        "csa_normal_low_pu": csa,
        "csa_extreme_low_pu": extreme,
        "p_undervolt_by_ev": p_undervolt,
        "min_v_p50_by_ev": swept["min_v_p50"],
        "min_v_p05_by_ev": min_v_p05,
        "min_v_p01_by_ev": swept["min_v_p01"],
        "min_v_worst_by_ev": min_v_worst,
        "reference_ev_per_home": ev_grid[ref],
        "p_undervolt_at_ref": p_undervolt[ref],
        "min_v_p05_at_ref": min_v_p05[ref],
        "min_v_worst_at_ref": min_v_worst[ref],
        "first_risk_ev_per_home": first_risk,
        "binding_cluster_size_at_ref": binding_size,
    }
    json_dir = PROJECT_OUTPUTS_DIR / "json"
    json_dir.mkdir(parents=True, exist_ok=True)
    out_path = json_dir / "voltage_risk_network.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    fig_paths = _figures(payload, PROJECT_OUTPUTS_DIR / "figures")

    summary = {
        "n_homes_total": n_homes_total,
        "n_cold_days": len(cold_days),
        "p_undervolt_at_ref": p_undervolt[ref],
        "min_v_p05_at_ref": min_v_p05[ref],
        "min_v_worst_at_ref": min_v_worst[ref],
        "first_risk_ev_per_home": first_risk,
        "binding_cluster_size_at_ref": binding_size,
    }
    return {"artifact_paths": [out_path, *fig_paths], "summary": summary}


def _figures(payload: dict[str, Any], figures_dir: Path) -> list[Path]:
    """Three-panel figure: P(undervoltage), voltage tail, first-risk."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    evs = payload["ev_per_home_grid"]
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(14.5, 4.3))

    ax1.plot(evs, payload["p_undervolt_by_ev"], "o-", color="C3")
    ax1.set_xlabel("EV/home")
    ax1.set_ylabel("P(network min LV V < CSA 0.917)")
    ax1.set_title("Network undervoltage probability")

    ax2.plot(evs, payload["min_v_p50_by_ev"], "o-", color="C0", label="median")
    ax2.plot(evs, payload["min_v_p05_by_ev"], "s--", color="C1", label="P5")
    ax2.plot(evs, payload["min_v_worst_by_ev"], "^:", color="C3", label="worst")
    ax2.axhline(payload["csa_normal_low_pu"], color="k", ls="--", lw=1,
                label="CSA 0.917")
    ax2.axhline(payload["csa_extreme_low_pu"], color="0.5", ls=":", lw=1,
                label="extreme 0.883")
    ax2.set_xlabel("EV/home")
    ax2.set_ylabel("network min LV voltage (pu)")
    ax2.set_title("Voltage tail vs adoption")
    ax2.legend(fontsize=7)

    ax3.plot(evs, payload["p_undervolt_by_ev"], "o-", color="C3")
    ax3.axhline(VOLTAGE_RISK_THRESHOLD, color="k", ls=":", lw=1,
                label=f"risk {VOLTAGE_RISK_THRESHOLD:g}")
    if payload["first_risk_ev_per_home"] is not None:
        ax3.axvline(payload["first_risk_ev_per_home"], color="C2", ls="--",
                    lw=1.5, label=f"first-risk {payload['first_risk_ev_per_home']:g}")
    ax3.set_xlabel("EV/home")
    ax3.set_ylabel("P(undervoltage)")
    ax3.set_title("First-risk adoption")
    ax3.legend(fontsize=8)

    fig.suptitle(
        "Full-net voltage-risk diagnostic: network LV undervoltage vs adoption",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    paths = []
    for suffix in (".png", ".pdf"):
        p = figures_dir / f"voltage_risk_network{suffix}"
        fig.savefig(p, dpi=200, bbox_inches="tight")
        paths.append(p)
    plt.close(fig)
    return paths


def run_stage() -> dict[str, Any]:
    """Run the full-net voltage-risk diagnostic and emit the platform report."""
    from gridalyn.projects.scripting import project_script

    script = project_script()
    derived = derive_voltage_network(script.cache_dir)
    warnings = [
        "DIAGNOSTIC ONLY — no flexibility. Full-network LV undervoltage "
        "probability + severity under EV adoption, MC over the EV fleet x cold "
        "days with balanced AC power flow on the HQ-sized network.",
        "SCOPE: the full sized network (validate_powerflow's family) — the "
        "cumulative MV + transformer + LV drop, unlike the governed feeder subnet "
        "which drops the ~0.05 pu MV feeder contribution and understates the risk.",
        "MODEL: uniform EV adoption (clustered is analyze_clustered_adoption); the "
        "per-home base is one deterministic realization by cluster size (the EV "
        "fleet + the cold-day weather are the stochastic axes); finite K_MC -> the "
        "probabilities carry Monte-Carlo sampling error.",
        "The deep-feeder residual (~0.91 pu) is inherent long-25 kV-MV-feeder drop "
        "held by LTC / regulators in reality, not conductor gauge — documented in "
        "the network-model verification.",
    ]
    return script.write_report(
        "voltage_risk_network_report",
        artifacts=[script.file_reference(p) for p in derived["artifact_paths"]],
        summary=derived["summary"],
        validation={"valid": True, "errors": [], "warnings": warnings},
    )


def main() -> None:
    """CLI entry point for the full-net voltage-risk diagnostic stage."""
    argparse.ArgumentParser(description=__doc__).parse_args()
    report = run_stage()
    s = report.get("summary", {})
    print(
        "Full-net voltage-risk diagnostic + report: P(undervoltage) "
        f"{s.get('p_undervolt_at_ref')} at 1 EV/home | min V P5 "
        f"{s.get('min_v_p05_at_ref')} worst {s.get('min_v_worst_at_ref')} pu | "
        f"first-risk {s.get('first_risk_ev_per_home')} EV/home | binds at "
        f"{s.get('binding_cluster_size_at_ref')}-home | "
        f"{s.get('n_cold_days')} cold days"
    )


if __name__ == "__main__":
    main()
