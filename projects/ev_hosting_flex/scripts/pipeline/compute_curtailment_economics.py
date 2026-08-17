"""Study-B non-wires economics: contract vs reinforcement (F4 of the migration).

Ports study-B Figs E/F onto the governed annual artifacts: the two-part
curtailment contract (``C_AVAIL_EV_YR`` availability + ``C_A_CURTAIL`` per kWh
curtailed) against the annualized transformer reinforcement
(``CAPEX_UPGRADE × CRF``), plus the zone-of-agreement panel (DSO
willingness-to-pay ceiling vs household foregone-energy floor) and the
break-even adoption. Runs ALONGSIDE the design-day economics stage until F6.
"""

from __future__ import annotations

import argparse
from typing import Any

import numpy as np

from gridalyn.projects.scripting import ProjectScript
from projects.ev_hosting_flex.scripts._annual import (
    feeder_rating,
    load_annual_tmy,
    simulate_curtailment,
)
from projects.ev_hosting_flex.scripts.config import (
    ANNUAL_RES_MINUTES,
    C_A_CURTAIL,
    C_AVAIL_EV_YR,
    C_RETAIL_KWH,
    CAPEX_UPGRADE,
    DISCOUNT_RATE,
    DTYPE,
    LIFE_YEARS,
    POWER_FACTOR,
    ROUND_DECIMALS,
    TRANSFORMER_KVA,
)

# SEAL-01: the BLAS thread cap lives in projects/ev_hosting_flex/scripts/__init__.py
# (imported before this stage under `{python} -m`).


_RATING_KW = float(TRANSFORMER_KVA) * float(POWER_FACTOR)


def capital_recovery_factor(rate: float, years: int) -> float:
    """Return the capital-recovery factor ``r(1+r)^L / ((1+r)^L − 1)``.

    Args:
        rate: Annual discount rate (> 0).
        years: Asset life in years (> 0).

    Returns:
        The CRF (per year).

    Raises:
        ValueError: If ``rate`` or ``years`` is not positive.
    """
    if rate <= 0.0 or years <= 0:
        raise ValueError(
            f"capital_recovery_factor needs rate > 0 and years > 0 "
            f"(got rate={rate}, years={years})."
        )
    growth = (1.0 + rate) ** years
    return rate * growth / (growth - 1.0)


def derive_curtailment_economics(script: ProjectScript) -> dict[str, Any]:
    data_dir = script.data_dir
    """Compute the contract-vs-reinforcement economics and persist them.

    Args:
        data_dir: Directory holding the F1 annual artifacts.
        json_dir: Governed JSON directory (reads F2 firm, writes results).

    Returns:
        Dict with ``artifact_paths`` and the report ``summary``.
    """
    base = np.load(data_dir / "base_annual.npy").astype(DTYPE)[0]
    pool = np.load(data_dir / "ev_fleet_annual.npy").astype(DTYPE)
    # Each hour is judged against the capability its OWN ambient allows
    # (RATING_CONVENTION). `cap` is the nameplate scalar kept for reporting;
    # `series` is what a load is actually compared against.
    cap, series = feeder_rating(load_annual_tmy())
    firm = int(
        script.read_json("outputs/json/firm_hosting_annual.json")["firm_ev_count"]
    )
    n_homes = int(
        script.read_json("outputs/reports/annual_mc_report.json")["summary"]["n_homes"]
    )
    pool_max = pool.shape[0]

    crf = capital_recovery_factor(float(DISCOUNT_RATE), int(LIFE_YEARS))
    reinf_annual = float(CAPEX_UPGRADE) * crf

    rows: list[dict[str, Any]] = []
    breakeven_n = pool_max  # last n where the contract still beats reinforcement
    for n in range(1, pool_max + 1):
        out = simulate_curtailment(
            base,
            pool[:n],
            np.ones(n, bool),
            cap,
            res_minutes=ANNUAL_RES_MINUTES,
            rating_series=series,
        )
        curt_kwh = float(out["curtailed_kwh_by_ev"].sum())
        contract = n * float(C_AVAIL_EV_YR) + float(C_A_CURTAIL) * curt_kwh
        pay_per_ev = contract / n
        ceiling_per_ev = reinf_annual / n
        floor_per_ev = float(C_RETAIL_KWH) * curt_kwh / n
        rows.append(
            {
                "n_evs": n,
                "adoption_percent": round(n / n_homes * 100.0, ROUND_DECIMALS),
                "curtailed_kwh": round(curt_kwh, ROUND_DECIMALS),
                "contract_cost_yr": round(contract, ROUND_DECIMALS),
                "pay_per_ev_yr": round(pay_per_ev, ROUND_DECIMALS),
                "dso_ceiling_per_ev_yr": round(ceiling_per_ev, ROUND_DECIMALS),
                "household_floor_per_ev_yr": round(floor_per_ev, ROUND_DECIMALS),
                "contract_beats_reinforcement": bool(contract <= reinf_annual),
                "zone_open": bool(ceiling_per_ev >= pay_per_ev),
            }
        )
    beating = [row["n_evs"] for row in rows if row["contract_beats_reinforcement"]]
    breakeven_n = int(beating[-1]) if beating else 0

    payload = {
        "firm_ev_count": firm,
        "crf": round(crf, ROUND_DECIMALS),
        "reinforcement_annual_yr": round(reinf_annual, ROUND_DECIMALS),
        "c_avail_ev_yr": float(C_AVAIL_EV_YR),
        "c_a_curtail_kwh": float(C_A_CURTAIL),
        "c_retail_kwh": float(C_RETAIL_KWH),
        "breakeven_ev_count": breakeven_n,
        "breakeven_adoption_percent": round(
            breakeven_n / n_homes * 100.0, ROUND_DECIMALS
        ),
        "curve": rows,
    }
    out_path_ref = script.write_json("outputs/json/curtailment_economics.json", payload)

    summary = {
        "reinforcement_annual_yr": payload["reinforcement_annual_yr"],
        "crf": payload["crf"],
        "breakeven_ev_count": breakeven_n,
        "breakeven_adoption_percent": payload["breakeven_adoption_percent"],
        "contract_cost_at_firm_plus_1_yr": (
            rows[firm]["contract_cost_yr"] if firm < len(rows) else None
        ),
        "pay_per_ev_at_pool_top_yr": rows[-1]["pay_per_ev_yr"],
        "n_homes": n_homes,
    }
    return {"artifact_paths": [out_path_ref], "summary": summary}


def run_stage() -> dict[str, Any]:
    """Run the curtailment-economics stage and emit the platform report.

    Returns:
        The platform report payload written via ``script.write_report``.
    """
    from gridalyn.projects.scripting import project_script

    script = project_script()
    derived = derive_curtailment_economics(script)
    return script.write_report(
        "curtailment_economics_report",
        artifacts=[
            p if isinstance(p, dict) else script.file_reference(p)
            for p in derived["artifact_paths"]
        ],
        summary=derived["summary"],
        validation={"valid": True, "errors": [], "warnings": []},
    )


def main() -> None:
    """CLI entry point for the curtailment-economics stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    report = run_stage()
    summary = report.get("summary", {})
    print(
        "Computed curtailment economics + report: "
        f"reinforcement ${summary.get('reinforcement_annual_yr')}/yr (CRF "
        f"{summary.get('crf')}), contract beats it up to "
        f"{summary.get('breakeven_ev_count')} EVs "
        f"({summary.get('breakeven_adoption_percent')}% adoption)"
    )


if __name__ == "__main__":
    main()
