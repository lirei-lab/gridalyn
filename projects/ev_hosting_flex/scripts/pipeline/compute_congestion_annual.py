"""Study-B annual firm hosting (F2 of the annual migration).

Derives the curtailment-free firm hosting count on the annual artifacts: firm =
the largest EV-pool prefix whose P95 cold-day evening loading stays at or below
``FIRM_P95_LIMIT_PERCENT`` (D-B5), plus the congested-hours diagnostics the
curtailment stage (F3) and economics (F4) build on. Runs ALONGSIDE the
design-day congestion stage until F6 retires it; emits its own
``firm_hosting_annual.json`` (the design-day ``firm_hosting.json`` is untouched).
"""

from __future__ import annotations

import argparse
from typing import Any

import numpy as np

from gridalyn.projects.scripting import ProjectScript
from projects.ev_hosting_flex.scripts._annual import (
    feeder_rating,
    firm_annual,
    load_annual_tmy,
    p95_cold_evening_loading,
    tmy_hour_of_day,
)
from projects.ev_hosting_flex.scripts.config import (
    ANNUAL_RES_MINUTES,
    DTYPE,
    POWER_FACTOR,
    ROUND_DECIMALS,
    TRANSFORMER_KVA,
)

# SEAL-01: the BLAS thread cap lives in projects/ev_hosting_flex/scripts/__init__.py
# (imported before this stage under `{python} -m`).


_RATING_KW = float(TRANSFORMER_KVA) * float(POWER_FACTOR)
"""Nameplate usable kW. The rating a load is JUDGED against comes from
``feeder_rating`` and may vary per step -- see ``RATING_CONVENTION``."""
_HOURS_PER_STEP = float(ANNUAL_RES_MINUTES) / 60.0


def derive_annual_congestion(script: ProjectScript) -> dict[str, Any]:
    data_dir = script.data_dir
    """Compute the annual firm count + congestion diagnostics and persist them.

    Args:
        data_dir: Directory holding the F1 annual artifacts.
        json_dir: Governed JSON output directory.

    Returns:
        Dict with ``artifact_paths`` and the report ``summary``.
    """
    base = np.load(data_dir / "base_annual.npy").astype(DTYPE)[0]
    pool = np.load(data_dir / "ev_fleet_annual.npy").astype(DTYPE)
    tday = np.load(data_dir / "tday_mean_c.npy").astype(DTYPE)
    # LOCAL phase anchor of array position 0 (the 2026-07-07 phase-bug fix):
    # the evening window is selected in local hours, not array positions.
    temp = load_annual_tmy()
    hod0 = tmy_hour_of_day(temp)
    # The rating a winter peak is judged against depends on the ambient of that
    # very hour (RATING_CONVENTION); `cap` is the scalar for reporting, `series`
    # the per-step limit the kernels actually apply.
    cap, series = feeder_rating(temp)
    limit = cap if series is None else series

    firm = firm_annual(
        base,
        pool,
        cap,
        tday,
        hod0=hod0,
        res_minutes=ANNUAL_RES_MINUTES,
        rating_series=series,
    )
    firm_n = int(firm["firm_ev_count"])
    n_homes_pool = pool.shape[0]

    # Congested-hours diagnostics per pool prefix (base floor at n=0); step
    # counts converted to real hours at the governed resolution.
    congested_hours = []
    cumulative = np.zeros(base.shape, dtype=DTYPE)
    congested_hours.append(
        round(float((base > limit).sum()) * _HOURS_PER_STEP, ROUND_DECIMALS)
    )
    for ev in range(pool.shape[0]):
        cumulative = cumulative + pool[ev]
        congested_hours.append(
            round(
                float(((base + cumulative) > limit).sum()) * _HOURS_PER_STEP,
                ROUND_DECIMALS,
            )
        )

    payload = {
        "firm_ev_count": firm_n,
        "firm_penetration": round(firm_n / n_homes_pool, ROUND_DECIMALS),
        "p95_cold_evening_curve": firm["p95_curve"],
        "p95_limit_percent": firm["limit_percent"],
        "congested_hours_per_year_curve": congested_hours,
        "base_floor_hours": congested_hours[0],
        "base_p95_cold_evening_percent": firm["p95_curve"][0],
        "feeder_transformer_modeled_kw": round(_RATING_KW, ROUND_DECIMALS),
        "horizon": "annual_8760h",
        "res_minutes": int(ANNUAL_RES_MINUTES),
        "rule": "p95_cold_evening_loading_le_limit",
    }
    firm_path_ref = script.write_json("outputs/json/firm_hosting_annual.json", payload)

    summary = {
        "firm_ev_count": firm_n,
        "base_p95_cold_evening_percent": firm["p95_curve"][0],
        "p95_at_firm_percent": firm["p95_curve"][firm_n],
        "p95_at_firm_plus_one_percent": (
            firm["p95_curve"][firm_n + 1]
            if firm_n + 1 < len(firm["p95_curve"])
            else None
        ),
        "base_floor_hours": congested_hours[0],
        "congested_hours_at_pool_top": congested_hours[-1],
        "rating_kw": round(_RATING_KW, ROUND_DECIMALS),
        "p95_base_check": round(
            p95_cold_evening_loading(
                base,
                cap,
                tday,
                hod0=hod0,
                res_minutes=ANNUAL_RES_MINUTES,
                rating_series=series,
            ),
            ROUND_DECIMALS,
        ),
    }
    return {"artifact_paths": [firm_path_ref], "summary": summary}


def run_stage() -> dict[str, Any]:
    """Run the annual congestion stage and emit the platform report.

    Returns:
        The platform report payload written via ``script.write_report``.
    """
    from gridalyn.projects.scripting import project_script

    script = project_script()
    derived = derive_annual_congestion(script)
    return script.write_report(
        "annual_congestion_report",
        artifacts=[
            p if isinstance(p, dict) else script.file_reference(p)
            for p in derived["artifact_paths"]
        ],
        summary=derived["summary"],
        validation={"valid": True, "errors": [], "warnings": []},
    )


def main() -> None:
    """CLI entry point for the annual congestion stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    report = run_stage()
    summary = report.get("summary", {})
    print(
        "Computed annual firm hosting + report: "
        f"firm_ev_count={summary.get('firm_ev_count')} "
        f"(P95 at firm {summary.get('p95_at_firm_percent')}% -> "
        f"{summary.get('p95_at_firm_plus_one_percent')}% at firm+1), "
        f"base_floor={summary.get('base_floor_hours')} h/yr"
    )


if __name__ == "__main__":
    main()
