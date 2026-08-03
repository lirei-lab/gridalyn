"""Study-B curtailment contract stage (F3 of the annual migration).

The mechanism headline: day-ahead the DSO forecasts and CALLS the contract for
predicted congested hours (user notice); in real time the backstop PREVENTS
charging of enrolled EVs just enough to hold the feeder at its rating (energy
not recovered), rotated fairly. Reliability comes from the backstop — the
forecast governs only the notice quality (no forecast-blindness by design).

Emitted headlines (ports of study-B Figs B/C/D/G, governed conventions):

* flexible hosting = largest pool prefix the full-enrollment backstop hosts
  with ZERO residual congestion beyond the base floor → expansion vs the
  annual firm (F2);
* curtailment price curve (% of EV energy curtailed vs count);
* enrollment sweep at 1 EV/home (the binding lever: residual h/yr vs ρ);
* notice quality per forecast sigma (planned / surprise / false-alarm);
* fairness: Jain index fair-rotation vs fixed-order + per-EV burden.

Runs ALONGSIDE the design-day flexibility stage until F6 retires it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Pitfall 2 (SEAL-01): cap the BLAS thread pool at module top.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from projects.ev_hosting_flex.scripts._annual import (  # noqa: E402
    feeder_rating,
    load_annual_tmy,
    simulate_curtailment,
)
from projects.ev_hosting_flex.scripts.config import (  # noqa: E402
    ANNUAL_RES_MINUTES,
    DTYPE,
    FC_SIGMAS,
    POWER_FACTOR,
    PROJECT_OUTPUTS_DIR,
    ROUND_DECIMALS,
    TRANSFORMER_KVA,
)

_RATING_KW = float(TRANSFORMER_KVA) * float(POWER_FACTOR)
_HOURS_PER_STEP = float(ANNUAL_RES_MINUTES) / 60.0

ENROLLMENT_GRID = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)
"""Enrollment fractions swept at 1 EV/home (study-B Fig B grid)."""


def _jain(x: np.ndarray) -> float:
    """Return the Jain fairness index of a non-negative burden vector."""
    total_sq = float((x**2).sum())
    if total_sq <= 0.0:
        return 1.0
    return float(x.sum() ** 2) / (len(x) * total_sq)


def derive_curtailment(data_dir: Path, json_dir: Path) -> dict[str, Any]:
    """Compute the curtailment-mechanism headlines and persist them.

    Args:
        data_dir: Directory holding the F1 annual artifacts.
        json_dir: Governed JSON directory (reads the F2 firm, writes results).

    Returns:
        Dict with ``artifact_paths`` and the report ``summary``.
    """
    base = np.load(data_dir / "base_annual.npy").astype(DTYPE)[0]
    pool = np.load(data_dir / "ev_fleet_annual.npy").astype(DTYPE)
    firm_payload = json.loads((json_dir / "firm_hosting_annual.json").read_text())
    firm = int(firm_payload["firm_ev_count"])
    # Each hour is judged against the capability its OWN ambient allows
    # (RATING_CONVENTION). `cap` is the nameplate scalar kept for reporting;
    # `limit` is what a load is actually compared against.
    cap, series = feeder_rating(load_annual_tmy())
    limit = cap if series is None else series
    base_floor = round(float((base > limit).sum()) * _HOURS_PER_STEP, ROUND_DECIMALS)
    pool_max = pool.shape[0]

    # ── Flexible hosting: full-enrollment backstop, zero residual beyond floor ─
    price_curve: list[float] = [0.0]
    residual_curve: list[float] = [base_floor]
    flexible = 0
    for n in range(1, pool_max + 1):
        out = simulate_curtailment(
            base,
            pool[:n],
            np.ones(n, bool),
            cap,
            res_minutes=ANNUAL_RES_MINUTES,
            rating_series=series,
        )
        energy = float(pool[:n].sum()) * _HOURS_PER_STEP
        price_curve.append(
            round(
                float(out["curtailed_kwh_by_ev"].sum()) / energy * 100.0, ROUND_DECIMALS
            )
        )
        residual_curve.append(round(float(out["residual_hours"]), ROUND_DECIMALS))
        if out["residual_hours"] <= base_floor + 1e-9:
            flexible = n
    expansion = (flexible / firm - 1.0) if firm > 0 else None

    # ── Enrollment sweep at 1 EV/home (the binding lever, study-B Fig B) ────
    annual_report = json.loads(
        (PROJECT_OUTPUTS_DIR / "reports" / "annual_mc_report.json").read_text()
    )
    n_lever = min(int(annual_report["summary"]["n_homes"]), pool_max)
    enrollment = []
    for rho in ENROLLMENT_GRID:
        n_enrolled = int(round(rho * n_lever))
        mask = np.zeros(n_lever, bool)
        mask[:n_enrolled] = True
        out = simulate_curtailment(
            base,
            pool[:n_lever],
            mask,
            cap,
            res_minutes=ANNUAL_RES_MINUTES,
            rating_series=series,
        )
        enrollment.append(
            {
                "rho": rho,
                "n_enrolled": n_enrolled,
                "residual_hours": round(float(out["residual_hours"]), ROUND_DECIMALS),
                "curtailed_kwh": round(
                    float(out["curtailed_kwh_by_ev"].sum()), ROUND_DECIMALS
                ),
            }
        )

    # ── Notice quality per forecast sigma (study-B Fig C) ──────────────────
    # ``called`` uses the ACTUAL EV aggregate on the forecast base: the only
    # day-ahead error channel is the temperature (study-B convention, D-B3).
    # All masks are at the governed step resolution (overlap fractions cancel).
    full = simulate_curtailment(
        base,
        pool[:n_lever],
        np.ones(n_lever, bool),
        cap,
        rating_series=series,
        res_minutes=ANNUAL_RES_MINUTES,
    )
    actual_steps = full["curtailed_steps"]
    ev_aggregate = pool[:n_lever].sum(axis=0)
    notice = {}
    for sigma in FC_SIGMAS:
        fc = np.load(data_dir / f"fc_base_sigma_{sigma:.1f}.npy").astype(DTYPE)
        called = (fc + ev_aggregate) > limit
        n_actual = max(int(actual_steps.sum()), 1)
        n_called = max(int(called.sum()), 1)
        notice[f"{sigma:.1f}"] = {
            "planned_percent": round(
                float((called & actual_steps).sum()) / n_actual * 100.0, ROUND_DECIMALS
            ),
            "surprise_percent": round(
                float((~called & actual_steps).sum()) / n_actual * 100.0,
                ROUND_DECIMALS,
            ),
            "false_alarm_percent": round(
                float((called & ~actual_steps).sum()) / n_called * 100.0,
                ROUND_DECIMALS,
            ),
        }

    # ── Fairness on the full pool (study-B Fig D) ──────────────────────────
    fair = simulate_curtailment(
        base,
        pool,
        np.ones(pool_max, bool),
        cap,
        rating_series=series,
        res_minutes=ANNUAL_RES_MINUTES,
    )
    unfair = simulate_curtailment(
        base,
        pool,
        np.ones(pool_max, bool),
        cap,
        fair=False,
        rating_series=series,
        res_minutes=ANNUAL_RES_MINUTES,
    )
    fairness = {
        "jain_fair": round(_jain(fair["curtailed_kwh_by_ev"]), ROUND_DECIMALS),
        "jain_fixed_order": round(_jain(unfair["curtailed_kwh_by_ev"]), ROUND_DECIMALS),
        "mean_curtailed_kwh_per_ev": round(
            float(fair["curtailed_kwh_by_ev"].mean()), ROUND_DECIMALS
        ),
        "mean_events_per_ev": round(float(fair["events_by_ev"].mean()), ROUND_DECIMALS),
        "total_curtailed_kwh": round(
            float(fair["curtailed_kwh_by_ev"].sum()), ROUND_DECIMALS
        ),
    }

    payload = {
        "firm_ev_count": firm,
        "flexible_ev_count": flexible,
        "hosting_expansion_percent": (
            round(expansion, ROUND_DECIMALS) if expansion is not None else None
        ),
        "curtailed_energy_percent_curve": price_curve,
        "residual_hours_curve": residual_curve,
        "base_floor_hours": base_floor,
        "enrollment_sweep_1ev_per_home": enrollment,
        "n_lever_evs": n_lever,
        "notice_quality_by_sigma": notice,
        "fairness": fairness,
        "rating_kw": round(_RATING_KW, ROUND_DECIMALS),
        "mechanism": "dayahead_notice_realtime_backstop_fair_rotation",
    }
    json_dir.mkdir(parents=True, exist_ok=True)
    out_path = json_dir / "curtailment_hosting.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    summary = {
        "firm_ev_count": firm,
        "flexible_ev_count": flexible,
        "hosting_expansion_percent": payload["hosting_expansion_percent"],
        "curtailed_energy_percent_at_flexible": price_curve[flexible],
        "residual_hours_at_flexible": residual_curve[flexible],
        "jain_fair": fairness["jain_fair"],
        "mean_events_per_ev": fairness["mean_events_per_ev"],
        "planned_percent_sigma_1.5": notice["1.5"]["planned_percent"],
        "surprise_percent_sigma_1.5": notice["1.5"]["surprise_percent"],
    }
    return {"artifact_paths": [out_path], "summary": summary}


def run_stage() -> dict[str, Any]:
    """Run the curtailment stage and emit the platform report.

    Returns:
        The platform report payload written via ``script.write_report``.
    """
    from gridalyn.projects.scripting import project_script

    script = project_script()
    derived = derive_curtailment(
        PROJECT_OUTPUTS_DIR / "data", PROJECT_OUTPUTS_DIR / "json"
    )
    return script.write_report(
        "curtailment_contracts_report",
        artifacts=[script.file_reference(p) for p in derived["artifact_paths"]],
        summary=derived["summary"],
        validation={"valid": True, "errors": [], "warnings": []},
    )


def main() -> None:
    """CLI entry point for the curtailment-contract stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    report = run_stage()
    summary = report.get("summary", {})
    print(
        "Applied curtailment contracts + report: "
        f"firm={summary.get('firm_ev_count')} -> flexible={summary.get('flexible_ev_count')} "
        f"(+{summary.get('hosting_expansion_percent')}), "
        f"curtailed={summary.get('curtailed_energy_percent_at_flexible')}% of EV energy, "
        f"Jain={summary.get('jain_fair')}, "
        f"notice(s=1.5): planned {summary.get('planned_percent_sigma_1.5')}% / "
        f"surprise {summary.get('surprise_percent_sigma_1.5')}%"
    )


if __name__ == "__main__":
    main()
