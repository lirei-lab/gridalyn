"""
03_stage2_realization_replay.py

Out-of-sample evaluation of the real-time (Stage 2) CLS dispatch: replays the
market engine against every Monte Carlo realization as the metered load, per
EV-adoption scenario. The resulting distribution (mean, P5/P50/P95) of
Soft/Hard CLS energy, hard share, and settlement approximates the expectation
over scenarios in the paper's two-stage formulation — unlike the headline
security-envelope dispatch, which treats the 95% worst case as the actual
load at every timestep.

Outputs: outputs/json/stage2_realization_summary.json
"""

import sys
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.operations.flexibility import (
    prepare_cls_market_replay_context,
    scenario_label,
    summarize_stage2_realizations,
)
from projects.flexibility_cls.scripts.config import (
    EV_PERCENTAGES,
    MARKET_CLEARING_INTERVAL_H,
    N_FEEDER_BLOCKS,
    P_LIMIT_KW,
    PARTICIPATION_RATE,
    RES_MINUTES,
    S_RATED_KVA,
    THETA_MAX,
)
from projects.flexibility_cls.scripts.thermal_forecast import build_thermal_forecast


def main():
    print("=" * 60)
    print("  [Step 3] Stage-2 Per-Realization Replay (E_omega)")
    print("=" * 60)

    data_dir = ROOT / "projects/flexibility_cls/outputs/data"
    out_dir = ROOT / "projects/flexibility_cls/outputs/json"
    out_dir.mkdir(exist_ok=True, parents=True)

    df_base = pd.read_parquet(data_dir / "substation_baseline_mc.parquet")
    df_ev = pd.read_parquet(data_dir / "substation_ev_capability_mc.parquet")
    thermal_forecast = build_thermal_forecast(len(df_base.index))

    payload: dict[str, object] = {
        "description": (
            "Real-time CLS dispatch replayed against each Monte Carlo "
            "realization as the metered load (out-of-sample Stage 2)."
        ),
        "n_realizations": int(df_base.shape[1]),
        "scenarios": {},
    }
    for index, ev_pct in enumerate(EV_PERCENTAGES):
        label = scenario_label(index, ev_pct)
        print(f"  Replaying {label} across {df_base.shape[1]} realizations...")
        if ev_pct == 0:
            payload["scenarios"][label] = {
                "n_realizations": int(df_base.shape[1]),
                "note": "no EV load; no CLS dispatch",
            }
            continue
        context = prepare_cls_market_replay_context(
            baseline_mw=df_base,
            ev_capability_mw=df_ev,
            thermal_forecast=thermal_forecast,
            ev_percent=ev_pct,
            resolution_minutes=RES_MINUTES,
            s_rated_kva=S_RATED_KVA,
            p_limit_kw=P_LIMIT_KW,
            theta_max=THETA_MAX,
            n_feeder_blocks=N_FEEDER_BLOCKS,
            participation_rate=PARTICIPATION_RATE,
            market_resolution_h=MARKET_CLEARING_INTERVAL_H,
        )
        summary = summarize_stage2_realizations(context)
        payload["scenarios"][label] = summary
        print(
            f"    soft {summary['soft_cls_mwh']['mean']:.3f} MWh | "
            f"hard {summary['hard_cls_mwh']['mean']:.3f} MWh | "
            f"hard share {100 * summary['hard_share']['mean']:.1f}% | "
            f"with backstop {summary['realizations_with_hard_cls']}/{summary['n_realizations']}"
        )

    out_path = out_dir / "stage2_realization_summary.json"
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"\n  -> Saved {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
