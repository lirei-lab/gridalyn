import sys
import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.datagen.grid.network import MVNetwork
from gridalyn.market.dso_dispatch import DSODispatcher
from gridalyn.market.engine import MarketSimulationEngine
from projects.flexibility_cls.scripts.config import RES_MINUTES, S_RATED_KVA, P_LIMIT_KW, THETA_MAX
from projects.flexibility_cls.scripts.thermal_forecast import build_thermal_forecast

PALETTE = {
    "buildings": "#3498db",  # Blue
    "evs_managed": "#e67e22", # Orange
    "soft_cls": "#2ecc71",   # Green
    "hard_cls": "#9b59b6",   # Purple
    "thermal_limit": "#c0392b" # Red
}

def main():
    print("Generating Stage 2: Real-Time Recourse Plot...")
    
    data_dir = ROOT / "projects/flexibility_cls/outputs/data"
    reports_dir = ROOT / "projects/flexibility_cls/outputs/reports"
    out_dir = ROOT / "projects/flexibility_cls/outputs/figures/05_stage4_realtime_dispatch"
    out_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    
    # Load stochastic data
    df_base = pd.read_parquet(data_dir / "substation_baseline_mc.parquet")
    df_ev = pd.read_parquet(data_dir / "substation_ev_capability_mc.parquet")
    
    p_base_kw_mean = df_base.mean(axis=1).values * 1000.0
    p_base_kw_std = df_base.std(axis=1).values * 1000.0
    
    # 40% EV penetration (Standardized for unified visual narrative showing Hard-CLS)
    p_ev_kw_mean = df_ev.mean(axis=1).values * 1000.0 * (40.0 / 30.0) 
    p_ev_kw_std = df_ev.std(axis=1).values * 1000.0 * (40.0 / 30.0)
    
    thermal_forecast = build_thermal_forecast(len(df_base.index))
    t_out_trace = thermal_forecast.ambient_c
    
    # Initialize components
    from gridalyn.datagen.grid.transformer_thermal import TransformerThermalModel
    thermal_model = TransformerThermalModel(theta_max=THETA_MAX, s_rated_kva=S_RATED_KVA)
    network = MVNetwork(thermal_model=thermal_model, p_rated_kw=P_LIMIT_KW)
    dt_h = RES_MINUTES / 60.0
    dispatcher = DSODispatcher(network=network, dt_man_h=dt_h, epsilon=0.05, stochastic_failure_rate=0.05)
    market_engine = MarketSimulationEngine(network=network, dispatcher=dispatcher)
    
    candidates = []
    selected = None

    for col_name in df_base.columns:
        realization_idx = int(col_name.rsplit("_", 1)[-1])
        p_base_kw_realized = df_base[col_name].values * 1000.0
        p_ev_kw_realized = df_ev[col_name].values * 1000.0 * (40.0 / 30.0)
        p_tot_kw_realized = p_base_kw_realized + p_ev_kw_realized

        # Run the engine (Real-Time Execution mode)
        df_candidate = market_engine.run(
            p_base_kw_mean=p_base_kw_mean,
            p_base_kw_std=p_base_kw_std,
            p_ev_kw_mean=p_ev_kw_mean,
            p_ev_kw_std=p_ev_kw_std,
            t_out_trace_c=t_out_trace,
            dt_man_h=dt_h,
            n_total_blocks=160,
            participation_rate=0.30, # 30% aggregator participation
            epsilon=0.05,            # 95% Confidence
            is_profiled=True, market_resolution_h=0.5,         # Profiled (block) contract
            p_tot_kw_realized=p_tot_kw_realized,
            p_ev_kw_realized=p_ev_kw_realized
        )

        soft_mwh = float(df_candidate["soft_cls_kw"].sum() * dt_h / 1000.0)
        hard_mwh = float(df_candidate["hard_cls_kw"].sum() * dt_h / 1000.0)
        rebound_mwh = float(df_candidate.get("rebound_kw", pd.Series(0.0, index=df_candidate.index)).sum() * dt_h / 1000.0)
        total_cls_mwh = soft_mwh + hard_mwh
        balance_score = 0.0 if max(soft_mwh, hard_mwh) <= 0.0 else min(soft_mwh, hard_mwh) / max(soft_mwh, hard_mwh)
        interest_score = total_cls_mwh * balance_score

        p_managed_kw = (
            p_base_kw_realized
            - df_candidate["soft_cls_kw"].values
            + p_ev_kw_realized
            - df_candidate["hard_cls_kw"].values
            + df_candidate.get("rebound_kw", pd.Series(0.0, index=df_candidate.index)).values
        )
        row = {
            "realization": col_name,
            "realization_index": realization_idx,
            "peak_unmanaged_mw": float(p_tot_kw_realized.max() / 1000.0),
            "peak_managed_mw": float(p_managed_kw.max() / 1000.0),
            "soft_cls_mwh": soft_mwh,
            "hard_cls_mwh": hard_mwh,
            "rebound_mwh": rebound_mwh,
            "soft_peak_mw": float(df_candidate["soft_cls_kw"].max() / 1000.0),
            "hard_peak_mw": float(df_candidate["hard_cls_kw"].max() / 1000.0),
            "n_soft_steps": int((df_candidate["soft_cls_kw"] > 1e-6).sum()),
            "n_hard_steps": int((df_candidate["hard_cls_kw"] > 1e-6).sum()),
            "soft_hard_balance_score": float(balance_score),
            "total_cls_mwh": float(total_cls_mwh),
            "interest_score": float(interest_score),
        }
        candidates.append(row)

        if selected is None or row["interest_score"] > selected["metrics"]["interest_score"]:
            selected = {
                "metrics": row,
                "df_res": df_candidate,
                "p_base_kw_realized": p_base_kw_realized,
                "p_ev_kw_realized": p_ev_kw_realized,
                "p_tot_kw_realized": p_tot_kw_realized,
            }

    if selected is None:
        raise RuntimeError("No Monte Carlo realization candidates were available")

    df_res = selected["df_res"]
    p_base_kw_realized = selected["p_base_kw_realized"]
    p_ev_kw_realized = selected["p_ev_kw_realized"]
    p_tot_kw_realized = selected["p_tot_kw_realized"]
    selected_metrics = selected["metrics"]

    selection_report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "scenario": "S4_40pct",
        "selection_rule": (
            "Maximize total CLS energy multiplied by Soft/Hard balance, so the "
            "paper realization visibly exercises both voluntary Soft-CLS and "
            "firm Hard-CLS recourse rather than only the most extreme hard event."
        ),
        "selected_realization": selected_metrics,
        "top_candidates": sorted(candidates, key=lambda row: row["interest_score"], reverse=True)[:10],
    }
    report_path = reports_dir / "stage_4_realtime_realization_selection.json"
    report_path.write_text(json.dumps(selection_report, indent=2))
    print(f"Selected {selected_metrics['realization']} for paper realization figure")
    print(f"Wrote selection report to {report_path}")
    
    t_hours = np.arange(len(p_base_kw_mean)) * (RES_MINUTES / 60)
    
    p_limit = thermal_forecast.p_limit_kw / 1000.0
        
    p_soft_cls = df_res["soft_cls_kw"].values / 1000.0
    p_hard_cls = df_res["hard_cls_kw"].values / 1000.0
    print("Soft-CLS [MWh]:", selected_metrics["soft_cls_mwh"])
    print("Hard-CLS [MWh]:", selected_metrics["hard_cls_mwh"])
    
    p_baseline_managed = (p_base_kw_realized / 1000.0) - p_soft_cls
    p_ev_managed = (p_ev_kw_realized / 1000.0) - p_hard_cls
    
    p_unmanaged_total = p_tot_kw_realized / 1000.0
    p_rebound = df_res["rebound_kw"].values / 1000.0 if "rebound_kw" in df_res.columns else np.zeros_like(p_unmanaged_total)
    
    # Create plot — golden-ratio aspect for visual consistency with Fig 5.
    GOLDEN = (1.0 + 5.0 ** 0.5) / 2.0
    _h = 7.0
    fig, ax = plt.subplots(figsize=(_h * GOLDEN, _h))
    
    # Stack arrays for filling
    y1 = p_baseline_managed
    y2 = y1 + p_ev_managed
    y3 = y2 + p_soft_cls
    y4 = y3 + p_hard_cls # Equals p_unmanaged_total
    y5 = p_unmanaged_total + p_rebound # True managed load during rebound
    
    ax.fill_between(t_hours, 0, y1, color=PALETTE["buildings"], alpha=0.8, label="Managed Building Load")
    ax.fill_between(t_hours, y1, y2, color=PALETTE["evs_managed"], alpha=0.8, label="Managed EV Charging")
    
    if np.max(p_rebound) > 0:
        ax.fill_between(t_hours, p_unmanaged_total, y5, color="#D9534F", alpha=0.8, hatch='\\\\', label="Post-Congestion Rebound")
        
    ax.fill_between(t_hours, y2, y3, color=PALETTE["soft_cls"], alpha=0.8, label="Soft-CLS (Firm DA Contract)")
    
    if np.max(p_hard_cls) > 0:
        ax.fill_between(t_hours, y3, y4, color=PALETTE["hard_cls"], alpha=0.8, label="Hard-CLS (Real-Time Recourse)")
    
    # Plot true realized load (without rebound)
    ax.plot(t_hours, p_unmanaged_total, color='black', lw=2, ls=(0, (5, 2, 1, 2)), alpha=0.7, label=r"Realized Unmanaged Load ($\omega$)")
    
    # Plot expected unmanaged load for reference
    p_tot_mean = p_base_kw_mean + p_ev_kw_mean
    ax.plot(t_hours, p_tot_mean / 1000.0, color='#4a4a4a', lw=2.5, ls='-', alpha=0.9, label=r"Expected Unmanaged Load ($\mu$)")
    
    # Plot true managed load line
    p_managed_total = y2 + p_rebound
    ax.plot(t_hours, p_managed_total, color='#2c3e50', lw=2, ls='-', label="True Managed Load")
    
    # Dynamic Thermal Limit
    ax.plot(t_hours, p_limit, color=PALETTE["thermal_limit"], lw=3, ls='-', label=r"Dynamic Thermal Limit ($\theta_H$)")
    
    # Formatting
    ax.set_ylabel("Substation Power Demand [MW]", fontsize=14)
    
    # Title removed — provided by LaTeX caption in paper
    
    ax.set_xlim(0, 28)
    y_min = np.min(p_base_kw_mean / 1000.0) * 0.85
    ax.set_ylim(y_min, np.max(p_unmanaged_total) * 1.1)
    
    ax.set_xticks(np.arange(0, 29, 4))

    # Elegant Time Formatting (HH:MM) starting from offset 12:00
    import matplotlib.ticker as ticker
    def format_time(x, pos):
        h = int(x % 24)
        m = int(round((x % 1) * 60))
        if m == 60: h = (h + 1) % 24; m = 0
        return f"{h:02d}:{m:02d}"
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(format_time))
    ax.set_xlabel("Time of Day [HH:MM]", fontsize=14)

    ax.grid(True, linestyle='--', alpha=0.4)
    ax.legend(loc="upper left", fontsize=12, framealpha=0.9)

    plt.tight_layout()

    out_path = out_dir / "plot_15_stage_2_realization.png"
    out_pdf_path = out_path.with_suffix(".pdf")
    fig.savefig(out_pdf_path, bbox_inches="tight")
    print(f"Saved PDF to {out_pdf_path}")

    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    print(f"Saved to {out_path}")

if __name__ == "__main__":
    main()
