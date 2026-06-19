"""
02_solve_capacity_allocation.py

Resolves the local capacity auction (Soft CLS and Hard CLS)
Invokes MarketSimulationEngine and clears the Multi-Block Soft-CLS supply curve.
Outputs: market_dispatch_timeseries.parquet, ev_summary_results.json
"""

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.operations import run_cls_capacity_allocation
from projects.flexibility_cls.scripts.config import (
    DELIVERY_FAILURE_RATE,
    EV_PERCENTAGES,
    HARD_CLS_PRICE,
    MARKET_CLEARING_INTERVAL_H,
    MAX_AGGREGATOR_COST,
    MIN_AGGREGATOR_COST,
    N_BUILDINGS,
    N_FEEDER_BLOCKS,
    NON_DELIVERY_PENALTY,
    P_LIMIT_KW,
    PARTICIPATION_RATE,
    PAY_FULL_BLOCK,
    RES_MINUTES,
    S_RATED_KVA,
    THETA_MAX,
)
from projects.flexibility_cls.scripts.pipeline._summary import summarize_array
from projects.flexibility_cls.scripts.thermal_forecast import build_thermal_forecast

# Downstream (Stage-01/02) arrays are pinned at a finer rounding floor than the
# jitter-prone Stage-00 MC arrays; the dispatch timeseries hash is a PRIMARY
# cross-environment tripwire.
STAGE_DOWNSTREAM_ROUND_DECIMALS = 6


def main():
    print("=" * 60)
    print("  [Step 2] Solve Market Allocation (Soft/Hard CLS)")
    print("=" * 60)

    data_dir = ROOT / "projects/flexibility_cls/outputs/data"
    out_dir = ROOT / "projects/flexibility_cls/outputs/json"
    out_dir.mkdir(exist_ok=True, parents=True)

    b_path = data_dir / "substation_baseline_mc.parquet"
    ev_path = data_dir / "substation_ev_capability_mc.parquet"

    if not b_path.exists() or not ev_path.exists():
        print(
            "[!] Parquet data not found. Please run 00_generate_stochastic_profiles.py first."
        )
        return

    df_base = pd.read_parquet(b_path)
    df_ev = pd.read_parquet(ev_path)

    thermal_forecast = build_thermal_forecast(len(df_base.index))
    result = run_cls_capacity_allocation(
        baseline_mw=df_base,
        ev_capability_mw=df_ev,
        ev_percentages=EV_PERCENTAGES,
        thermal_forecast=thermal_forecast,
        n_buildings=N_BUILDINGS,
        n_feeder_blocks=N_FEEDER_BLOCKS,
        participation_rate=PARTICIPATION_RATE,
        resolution_minutes=RES_MINUTES,
        s_rated_kva=S_RATED_KVA,
        p_limit_kw=P_LIMIT_KW,
        theta_max=THETA_MAX,
        market_clearing_interval_h=MARKET_CLEARING_INTERVAL_H,
        dispatch_ev_percent=40,
        reference_price_ev_percent=20,
        stochastic_failure_rate=DELIVERY_FAILURE_RATE,
        hard_cls_price=HARD_CLS_PRICE,
        non_delivery_penalty=NON_DELIVERY_PENALTY,
        min_aggregator_cost=MIN_AGGREGATOR_COST,
        max_aggregator_cost=MAX_AGGREGATOR_COST,
        pay_full_block=PAY_FULL_BLOCK,
    )

    for ev_pct in EV_PERCENTAGES:
        scenario_key = f"S{EV_PERCENTAGES.index(ev_pct)}_{ev_pct}pct"
        values = result.summary[scenario_key]
        print(f"\n  === Scenario S{EV_PERCENTAGES.index(ev_pct)} ({ev_pct}% EV) ===")
        print(f"      Unmanaged Peak: {values['unmanaged_peak_mw']:.2f} MW")
        print(f"      Managed Peak:   {values['managed_peak_mw']:.2f} MW")
        print(f"      Soft CLS:       {values['total_soft_cls_mwh']:.2f} MWh")
        print(f"      Hard CLS:       {values['total_hard_cls_mwh']:.2f} MWh")
        print(f"      Rebound:        {values['total_rebound_mwh']:.2f} MWh")
        print(f"      Net Settlement: ${values['total_market_settlement_usd']:.2f}")

    with open(out_dir / "ev_summary_results.json", "w") as f:
        json.dump(result.summary, f, indent=4)

    result.dispatch_timeseries.to_parquet(
        data_dir / "market_dispatch_timeseries.parquet",
        index=False,
    )

    # Stage-02 boundary summary: the dispatch timeseries is the PRIMARY tripwire
    # array; allocation totals are recorded here per scenario. This is the
    # stage-boundary summary, kept in a separate file from the envelope headline
    # (ev_summary_results.json) so envelope and replay quantities never share a
    # source (D-04).
    allocation_totals = {
        scenario_key: {
            "total_soft_cls_mwh": float(values["total_soft_cls_mwh"]),
            "total_hard_cls_mwh": float(values["total_hard_cls_mwh"]),
            "total_rebound_mwh": float(values["total_rebound_mwh"]),
        }
        for scenario_key, values in result.summary.items()
        if isinstance(values, dict) and "total_soft_cls_mwh" in values
    }
    allocation_summary = {
        "market_dispatch_timeseries": summarize_array(
            result.dispatch_timeseries.to_numpy(),
            round_decimals=STAGE_DOWNSTREAM_ROUND_DECIMALS,
        ),
        "allocation_totals": allocation_totals,
    }
    summary_path = out_dir / "stage02_allocation_summary.json"
    summary_path.write_text(
        json.dumps(allocation_summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(f"\n  -> Results dumped to {out_dir / 'ev_summary_results.json'}")
    print(
        f"  -> Dispatch timeseries saved to {data_dir / 'market_dispatch_timeseries.parquet'}"
    )
    print("  ✓ Step 2 Complete\n")


if __name__ == "__main__":
    main()
