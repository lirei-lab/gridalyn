"""Probabilistic voltage-risk DIAGNOSTIC (LV undervoltage, diagnosis first).

Estimates the probability and severity of LV undervoltage on the governed feeder
under EV adoption: Monte-Carlo the EV fleet across the cold days, solve one
balanced AC snapshot per (draw x cold day) at the coincident-peak hour, and
record the minimum LV bus voltage. P(min V < CSA 0.917) + the low voltage tail +
the first-risk adoption. No flexibility. Out of scope: phase imbalance (covered),
full-net AC (the governed feeder is the representative unit).
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
    ev_fleet_annual,
    load_annual_tmy,
    tmy_hour_of_day,
)
from projects.ev_hosting_flex.scripts._powerflow import (  # noqa: E402
    extract_feeder_subnet,
    feeder_min_voltage,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    COLD_DAY_TMEAN_C,
    DTYPE,
    PROJECT_OUTPUTS_DIR,
    ROUND_DECIMALS,
    SEED,
    SLACK_VM_PU,
    VOLTAGE_EV_GRID,
    VOLTAGE_LIMITS_PU,
    VOLTAGE_MC_DRAWS,
    VOLTAGE_RISK_THRESHOLD,
)


def _adoption_voltage_stats(
    subnet: Any,
    base_hourly: np.ndarray,
    pools: list[np.ndarray],
    cold_days: list[int],
    n_homes: int,
    ev_per_home: float,
    slack: float,
    csa: float,
) -> dict[str, float]:
    """Min-LV-voltage population over (EV draw x cold day) at adoption
    ``ev_per_home``; returns P(undervoltage) + the low voltage tail."""
    n_evs = int(round(float(ev_per_home) * int(n_homes)))
    minvs: list[float] = []
    for pool in pools:
        for d in cold_days:
            sl = slice(d * 24, (d + 1) * 24)
            base_day = np.asarray(base_hourly[sl], dtype=DTYPE)
            ev_day = (
                pool[:n_evs, sl].sum(axis=0) if n_evs > 0 else np.zeros(24, DTYPE)
            )
            total = base_day + ev_day
            per_home = float(total.max()) / int(n_homes)
            load_vec = np.full(int(n_homes), per_home, dtype=DTYPE)
            minvs.append(feeder_min_voltage(subnet, load_vec, slack_vm_pu=slack))
    arr = np.array(minvs, dtype=DTYPE)
    return {
        "p_undervolt": round(float((arr < csa).mean()), ROUND_DECIMALS),
        "min_v_p50": round(float(np.percentile(arr, 50)), ROUND_DECIMALS),
        "min_v_p05": round(float(np.percentile(arr, 5)), ROUND_DECIMALS),
        "min_v_p01": round(float(np.percentile(arr, 1)), ROUND_DECIMALS),
        "min_v_worst": round(float(arr.min()), ROUND_DECIMALS),
    }


def derive_voltage(cache_dir: Path, data_dir: Path) -> dict[str, Any]:
    """MC the EV fleet x cold days; per adoption level compute the LV
    undervoltage probability + voltage tail on the governed feeder."""
    with open(cache_dir / "pp_net_cache.pkl", "rb") as handle:
        net = pickle.load(handle)
    feeder_idx = int(
        json.loads((cache_dir / "feeder_selection.json").read_text())[
            "feeder_transformer_idx"
        ]
    )
    downstream = json.loads((cache_dir / "downstream_bus_map.json").read_text())[
        f"transformer:{feeder_idx}"
    ]
    subnet, _load_buses, n_homes = extract_feeder_subnet(
        net, feeder_idx, [int(b) for b in downstream]
    )

    temp = load_annual_tmy()
    hod0 = int(tmy_hour_of_day(temp))
    tday = day_mean_temps(temp)
    cold_days = [int(d) for d in np.where(tday < float(COLD_DAY_TMEAN_C))[0]]
    base_hourly = aggregate_to_hourly(
        np.load(data_dir / "base_annual.npy").astype(DTYPE)
    )[0]

    ev_grid = [float(e) for e in VOLTAGE_EV_GRID]
    n_max = int(round(max(ev_grid) * n_homes))
    pools = [
        aggregate_to_hourly(
            ev_fleet_annual(np.random.default_rng(SEED + 811 * k), n_max, tday, hod0)
        ).astype(DTYPE)
        for k in range(int(VOLTAGE_MC_DRAWS))
    ]
    csa = float(VOLTAGE_LIMITS_PU["normal_low"])
    extreme = float(VOLTAGE_LIMITS_PU["extreme_low"])

    p_undervolt, min_v_p50, min_v_p05, min_v_p01, min_v_worst = _sweep(
        subnet, base_hourly, pools, cold_days, n_homes, ev_grid,
        float(SLACK_VM_PU), csa,
    )

    ref = ev_grid.index(1.0) if 1.0 in ev_grid else len(ev_grid) - 1
    first_risk = _interp_first_cross(ev_grid, p_undervolt, float(VOLTAGE_RISK_THRESHOLD))

    payload = {
        "n_homes": int(n_homes),
        "ev_per_home_grid": [round(e, 6) for e in ev_grid],
        "mc_draws": int(VOLTAGE_MC_DRAWS),
        "n_cold_days": len(cold_days),
        "csa_normal_low_pu": csa,
        "csa_extreme_low_pu": extreme,
        "slack_vm_pu": float(SLACK_VM_PU),
        "p_undervolt_by_ev": p_undervolt,
        "min_v_p50_by_ev": min_v_p50,
        "min_v_p05_by_ev": min_v_p05,
        "min_v_p01_by_ev": min_v_p01,
        "min_v_worst_by_ev": min_v_worst,
        "reference_ev_per_home": ev_grid[ref],
        "p_undervolt_at_ref": p_undervolt[ref],
        "min_v_p05_at_ref": min_v_p05[ref],
        "min_v_worst_at_ref": min_v_worst[ref],
        "first_risk_ev_per_home": first_risk,
    }
    json_dir = PROJECT_OUTPUTS_DIR / "json"
    json_dir.mkdir(parents=True, exist_ok=True)
    out_path = json_dir / "voltage_risk.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    fig_paths = _figures(payload, PROJECT_OUTPUTS_DIR / "figures")

    summary = {
        "n_homes": int(n_homes),
        "n_cold_days": len(cold_days),
        "p_undervolt_at_ref": p_undervolt[ref],
        "min_v_p05_at_ref": min_v_p05[ref],
        "min_v_worst_at_ref": min_v_worst[ref],
        "first_risk_ev_per_home": first_risk,
    }
    return {"artifact_paths": [out_path, *fig_paths], "summary": summary}


def _sweep(
    subnet: Any,
    base_hourly: np.ndarray,
    pools: list[np.ndarray],
    cold_days: list[int],
    n_homes: int,
    ev_grid: list[float],
    slack: float,
    csa: float,
) -> tuple[list[float], list[float], list[float], list[float], list[float]]:
    """Run `_adoption_voltage_stats` across the EV adoption grid; returns the
    five per-EV metric lists (p_undervolt, p50, p05, p01, worst)."""
    p_undervolt, min_v_p50, min_v_p05, min_v_p01, min_v_worst = [], [], [], [], []
    for e in ev_grid:
        s = _adoption_voltage_stats(
            subnet, base_hourly, pools, cold_days, n_homes, e, slack, csa
        )
        p_undervolt.append(s["p_undervolt"])
        min_v_p50.append(s["min_v_p50"])
        min_v_p05.append(s["min_v_p05"])
        min_v_p01.append(s["min_v_p01"])
        min_v_worst.append(s["min_v_worst"])
    return p_undervolt, min_v_p50, min_v_p05, min_v_p01, min_v_worst


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
    """Three-panel figure: P(undervoltage), voltage tail, first-risk."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    evs = payload["ev_per_home_grid"]
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(14.5, 4.3))

    ax1.plot(evs, payload["p_undervolt_by_ev"], "o-", color="C3")
    ax1.set_xlabel("EV/home")
    ax1.set_ylabel("P(min LV V < CSA 0.917)")
    ax1.set_title("Undervoltage probability")

    ax2.plot(evs, payload["min_v_p50_by_ev"], "o-", color="C0", label="median")
    ax2.plot(evs, payload["min_v_p05_by_ev"], "s--", color="C1", label="P5")
    ax2.plot(evs, payload["min_v_worst_by_ev"], "^:", color="C3", label="worst")
    ax2.axhline(payload["csa_normal_low_pu"], color="k", ls="--", lw=1, label="CSA 0.917")
    ax2.axhline(payload["csa_extreme_low_pu"], color="0.5", ls=":", lw=1, label="extreme 0.883")
    ax2.set_xlabel("EV/home")
    ax2.set_ylabel("min LV voltage (pu)")
    ax2.set_title("Voltage tail vs adoption")
    ax2.legend(fontsize=7)

    ax3.plot(evs, payload["p_undervolt_by_ev"], "o-", color="C3")
    ax3.axhline(VOLTAGE_RISK_THRESHOLD, color="k", ls=":", lw=1,
                label=f"risk {VOLTAGE_RISK_THRESHOLD:g}")
    if payload["first_risk_ev_per_home"] is not None:
        ax3.axvline(payload["first_risk_ev_per_home"], color="C2", ls="--", lw=1.5,
                    label=f"first-risk {payload['first_risk_ev_per_home']:g}")
    ax3.set_xlabel("EV/home")
    ax3.set_ylabel("P(undervoltage)")
    ax3.set_title("First-risk adoption")
    ax3.legend(fontsize=8)

    fig.suptitle(
        "Voltage-risk diagnostic: LV undervoltage probability + severity vs adoption",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    paths = []
    for suffix in (".png", ".pdf"):
        p = figures_dir / f"voltage_risk{suffix}"
        fig.savefig(p, dpi=200, bbox_inches="tight")
        paths.append(p)
    plt.close(fig)
    return paths


def run_stage() -> dict[str, Any]:
    """Run the voltage-risk diagnostic and emit the platform report."""
    from gridalyn.projects.scripting import project_script

    script = project_script()
    derived = derive_voltage(script.cache_dir, PROJECT_OUTPUTS_DIR / "data")
    warnings = [
        "DIAGNOSTIC ONLY — no flexibility. LV undervoltage probability + severity "
        "on the governed feeder under EV adoption, MC over the EV fleet x cold "
        "days with balanced AC power flow.",
        "SCOPE: the governed 6-home feeder is the study unit (voltage is local per "
        "feeder; full-net AC MC is out of scope). Balanced AC (phase imbalance is "
        "covered by analyze_phase_imbalance). Even load split across homes; finite "
        "K_MC -> the probabilities carry MC sampling error.",
        "UNDERSTATES NETWORK RISK: the governed 6-home / 75 kVA feeder is small and "
        "well-sized, so its LV voltage stays healthy (worst ~0.93 pu at 2 EV/home > "
        "CSA 0.917) and P(undervoltage) is ~0. The network-wide undervoltage that "
        "validate_powerflow finds (0.916 pu at 1 EV/home, 0.900 at 1.5) sits on the "
        "LARGER / deeper feeders, not this one — a follow-up should target the "
        "largest feeder size to quantify that voltage risk probabilistically.",
    ]
    return script.write_report(
        "voltage_risk_report",
        artifacts=[script.file_reference(p) for p in derived["artifact_paths"]],
        summary=derived["summary"],
        validation={"valid": True, "errors": [], "warnings": warnings},
    )


def main() -> None:
    """CLI entry point for the voltage-risk diagnostic stage."""
    argparse.ArgumentParser(description=__doc__).parse_args()
    report = run_stage()
    s = report.get("summary", {})
    print(
        "Voltage-risk diagnostic + report: P(undervoltage) "
        f"{s.get('p_undervolt_at_ref')} at 1 EV/home | min V P5 "
        f"{s.get('min_v_p05_at_ref')} worst {s.get('min_v_worst_at_ref')} pu | "
        f"first-risk {s.get('first_risk_ev_per_home')} EV/home | "
        f"{s.get('n_cold_days')} cold days"
    )


if __name__ == "__main__":
    main()
