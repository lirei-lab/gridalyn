"""Phase-imbalance DIAGNOSTIC (3-phase MV, diagnosis before solutions).

The HQ LV is single-phase 240 V split-phase; the phase imbalance is at 25 kV MV,
where single-phase pole transformers are spread across the three phases. This
stage models that with runpp_3ph: each pole transformer is a single-phase load on
its MV bus (round-robin phase), carrying its cold coincident peak (base + MC EV
adoption). Stochastic EV adoption that clusters on one phase undervolts it —
invisible in the balanced model. No flexibility. Out of scope: the single-phase
LV, full-net LV 3-phase.
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
    to_three_phase_mv,
    vuf,
)
from projects.ev_hosting_flex.scripts.pipeline.validate_powerflow import (  # noqa: E402
    size_network_to_load,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    DTYPE,
    PHASE_EV_GRID,
    PHASE_MC_DRAWS,
    PHASE_R0_MULT,
    PHASE_RISK_THRESHOLD,
    PHASE_X0_MULT,
    POWER_FACTOR,
    PROJECT_OUTPUTS_DIR,
    ROUND_DECIMALS,
    SEED,
    VOLTAGE_LIMITS_PU,
)


def _solve_phase_min_v(
    mv: Any,
    pole_to_mv: dict[int, int],
    load_kw_by_trafo: dict[int, float],
    *,
    balanced: bool,
) -> dict[str, float]:
    """Place each transformer's load and solve runpp_3ph; return min per-phase
    voltage + VUF over the MV buses. ``balanced`` splits each load equally across
    the phases; otherwise it is single-phase, round-robin by transformer index."""
    import pandapower as pp

    mv.asymmetric_load = mv.asymmetric_load.iloc[0:0]
    pf = float(POWER_FACTOR)
    qf = float(np.tan(np.arccos(pf)))
    for i, t in enumerate(sorted(pole_to_mv)):
        kw = float(load_kw_by_trafo.get(t, 0.0))
        if balanced:
            p = [kw / 3.0 / 1000.0] * 3
        else:
            p = [0.0, 0.0, 0.0]
            p[i % 3] = kw / 1000.0
        pp.create_asymmetric_load(
            mv, bus=int(pole_to_mv[t]), p_a_mw=p[0], p_b_mw=p[1], p_c_mw=p[2],
            q_a_mvar=p[0] * qf, q_b_mvar=p[1] * qf, q_c_mvar=p[2] * qf,
        )
    pp.runpp_3ph(mv)
    mv_buses = list(pole_to_mv.values())
    v = mv.res_bus_3ph.loc[mv_buses, ["vm_a_pu", "vm_b_pu", "vm_c_pu"]]
    worst = v.min(axis=1).idxmin()
    row = v.loc[worst]
    return {
        "min_vm_pu": float(v.min().min()),
        "vuf": float(vuf(row["vm_a_pu"], row["vm_b_pu"], row["vm_c_pu"])),
    }


def _cold_peak_by_size(sizing: dict[str, Any]) -> dict[int, float]:
    """Cold coincident peak (kW) of a size-h transformer = max of h*per-home."""
    base_by_size = sizing["base_by_size"]
    return {int(h): float((int(h) * base_by_size[int(h)]).max()) for h in base_by_size}


def derive_phase(cache_dir: Path, data_dir: Path) -> dict[str, Any]:
    """MC EV adoption x adoption sweep; runpp_3ph unbalanced vs balanced."""
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
    peak_by_size = _cold_peak_by_size(sizing)
    size_by_trafo = sizing["size_by_trafo"]

    # per-EV cold evening peak (kW) from the fixed pool
    pool = aggregate_to_hourly(
        np.load(data_dir / "ev_fleet_annual.npy").astype(DTYPE)
    )
    ev_day = np.roll(
        pool[:, design_day * 24 : (design_day + 1) * 24].mean(axis=0), int(hod0)
    )
    ev_peak_kw = float(ev_day.max())

    mv, pole_to_mv = to_three_phase_mv(
        net, r0_mult=float(PHASE_R0_MULT), x0_mult=float(PHASE_X0_MULT)
    )
    trafos = sorted(pole_to_mv)
    homes = {t: int(size_by_trafo[t]) for t in trafos}
    base_kw = {t: peak_by_size[homes[t]] for t in trafos}
    csa = float(VOLTAGE_LIMITS_PU["normal_low"])
    ev_grid = [float(e) for e in PHASE_EV_GRID]

    p_undervolt, worst_vuf, min_v_p50, min_v_worst, balanced_min_v = [], [], [], [], []
    for e in ev_grid:
        bal = _solve_phase_min_v(
            mv, pole_to_mv, {t: base_kw[t] + e * homes[t] * ev_peak_kw for t in trafos},
            balanced=True,
        )
        balanced_min_v.append(round(bal["min_vm_pu"], ROUND_DECIMALS))
        pu, wv, p50, pworst = _scenario_stats(
            mv, pole_to_mv, base_kw, homes, e, ev_peak_kw, csa
        )
        p_undervolt.append(pu)
        worst_vuf.append(wv)
        min_v_p50.append(p50)
        min_v_worst.append(pworst)

    ref = ev_grid.index(1.0) if 1.0 in ev_grid else len(ev_grid) - 1
    first_risk = _interp_first_cross(ev_grid, p_undervolt, float(PHASE_RISK_THRESHOLD))
    balanced_gap = round(balanced_min_v[ref] - min_v_worst[ref], ROUND_DECIMALS)

    payload = {
        "n_pole_trafos": len(trafos),
        "ev_per_home_grid": [round(e, 6) for e in ev_grid],
        "mc_draws": int(PHASE_MC_DRAWS),
        "csa_normal_low_pu": csa,
        "r0_mult": float(PHASE_R0_MULT),
        "x0_mult": float(PHASE_X0_MULT),
        "p_undervolt_by_ev": p_undervolt,
        "worst_vuf_by_ev": worst_vuf,
        "min_v_p50_by_ev": min_v_p50,
        "min_v_worst_by_ev": min_v_worst,
        "balanced_min_v_by_ev": balanced_min_v,
        "reference_ev_per_home": ev_grid[ref],
        "p_undervolt_at_ref": p_undervolt[ref],
        "worst_vuf_at_ref": worst_vuf[ref],
        "balanced_gap_pu": balanced_gap,
        "first_risk_ev_per_home": first_risk,
    }
    json_dir = PROJECT_OUTPUTS_DIR / "json"
    json_dir.mkdir(parents=True, exist_ok=True)
    out_path = json_dir / "phase_imbalance.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    fig_paths = _figures(payload, PROJECT_OUTPUTS_DIR / "figures")

    summary = {
        "n_pole_trafos": len(trafos),
        "p_undervolt_at_ref": p_undervolt[ref],
        "worst_vuf_at_ref": worst_vuf[ref],
        "balanced_gap_pu": balanced_gap,
        "first_risk_ev_per_home": first_risk,
    }
    return {"artifact_paths": [out_path, *fig_paths], "summary": summary}


def _scenario_stats(
    mv: Any,
    pole_to_mv: dict[int, int],
    base_kw: dict[int, float],
    homes: dict[int, int],
    e: float,
    ev_peak_kw: float,
    csa: float,
) -> tuple[float, float, float, float]:
    """Run PHASE_MC_DRAWS unbalanced solves at adoption ``e``; return
    (p_undervolt, worst_vuf, min_v_p50, min_v_worst)."""
    trafos = sorted(pole_to_mv)
    minvs, vufs = [], []
    for k in range(int(PHASE_MC_DRAWS)):
        rng = np.random.default_rng(SEED + 7919 * int(e * 100) + k)
        loads = {
            t: base_kw[t] + float(rng.poisson(e * homes[t])) * ev_peak_kw
            for t in trafos
        }
        r = _solve_phase_min_v(mv, pole_to_mv, loads, balanced=False)
        minvs.append(r["min_vm_pu"])
        vufs.append(r["vuf"])
    minvs_arr = np.array(minvs)
    p_undervolt = round(float((minvs_arr < csa).mean()), ROUND_DECIMALS)
    worst_vuf = round(float(np.max(vufs)), ROUND_DECIMALS)
    min_v_p50 = round(float(np.percentile(minvs_arr, 50)), ROUND_DECIMALS)
    min_v_worst = round(float(minvs_arr.min()), ROUND_DECIMALS)
    return p_undervolt, worst_vuf, min_v_p50, min_v_worst


def _interp_first_cross(
    xs: list[float], ys: list[float], target: float
) -> float | None:
    """Smallest x where (increasing) ys first crosses target; interpolated."""
    for i in range(1, len(xs)):
        if ys[i - 1] < target <= ys[i]:
            return round(
                xs[i - 1] + (target - ys[i - 1]) * (xs[i] - xs[i - 1])
                / (ys[i] - ys[i - 1]),
                ROUND_DECIMALS,
            )
    if ys and ys[0] >= target:
        return round(xs[0], ROUND_DECIMALS)
    return None


def _figures(payload: dict[str, Any], figures_dir: Path) -> list[Path]:
    """Three-panel figure: P(phase undervoltage), VUF, unbalanced vs balanced."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    evs = payload["ev_per_home_grid"]
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(14.5, 4.3))

    ax1.plot(evs, payload["p_undervolt_by_ev"], "o-", color="C3")
    ax1.set_xlabel("EV/home")
    ax1.set_ylabel("P(any MV phase < CSA)")
    ax1.set_title("Phase undervoltage probability")

    ax2.plot(evs, payload["worst_vuf_by_ev"], "o-", color="C1")
    ax2.set_xlabel("EV/home")
    ax2.set_ylabel("worst voltage unbalance (%)")
    ax2.set_title("Voltage unbalance vs adoption")

    ax3.plot(evs, payload["balanced_min_v_by_ev"], "s--", color="C0", label="balanced")
    ax3.plot(evs, payload["min_v_worst_by_ev"], "o-", color="C3",
             label="unbalanced (worst)")
    ax3.axhline(payload["csa_normal_low_pu"], color="k", ls=":", lw=1,
                label="CSA 0.917")
    ax3.set_xlabel("EV/home")
    ax3.set_ylabel("min MV phase voltage (pu)")
    ax3.set_title("Balanced model hides the phase sag")
    ax3.legend(fontsize=8)

    fig.suptitle(
        "Phase-imbalance diagnostic (25 kV MV, single-phase pole transformers)",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    paths = []
    for suffix in (".png", ".pdf"):
        p = figures_dir / f"phase_imbalance{suffix}"
        fig.savefig(p, dpi=200, bbox_inches="tight")
        paths.append(p)
    plt.close(fig)
    return paths


def run_stage() -> dict[str, Any]:
    """Run the phase-imbalance diagnostic and emit the platform report."""
    from gridalyn.projects.scripting import project_script

    script = project_script()
    derived = derive_phase(script.cache_dir, PROJECT_OUTPUTS_DIR / "data")
    warnings = [
        "DIAGNOSTIC ONLY — no flexibility. Models the 25 kV MV phase imbalance "
        "(single-phase pole transformers across 3 phases); stochastic EV adoption "
        "clustering on a phase undervolts it, invisible in the balanced model.",
        "ZERO-SEQUENCE PARAMS are standard multipliers (r0/x0), not measured — "
        "calibratable. Pole transformers are collapsed to their aggregate MV load "
        "(the single-phase LV, balanced within the transformer, is out of scope). "
        "Round-robin transformer-to-phase assignment; the imbalance is EV-driven.",
    ]
    return script.write_report(
        "phase_imbalance_report",
        artifacts=[script.file_reference(p) for p in derived["artifact_paths"]],
        summary=derived["summary"],
        validation={"valid": True, "errors": [], "warnings": warnings},
    )


def main() -> None:
    """CLI entry point for the phase-imbalance diagnostic stage."""
    argparse.ArgumentParser(description=__doc__).parse_args()
    report = run_stage()
    s = report.get("summary", {})
    print(
        "Phase-imbalance diagnostic + report: P(phase undervoltage) "
        f"{s.get('p_undervolt_at_ref')} at 1 EV/home | worst VUF "
        f"{s.get('worst_vuf_at_ref')}% | balanced-vs-unbalanced gap "
        f"{s.get('balanced_gap_pu')} pu | first-risk {s.get('first_risk_ev_per_home')} "
        f"EV/home | {s.get('n_pole_trafos')} pole trafos"
    )


if __name__ == "__main__":
    main()
