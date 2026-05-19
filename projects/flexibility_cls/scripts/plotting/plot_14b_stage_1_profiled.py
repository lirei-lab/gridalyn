import sys
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.datagen.grid.network import MVNetwork
from gridalyn.market.dso_dispatch import DSODispatcher
from gridalyn.datagen.data.weather import download_tmy, select_peak_load_day
from gridalyn.market.engine import MarketSimulationEngine
from projects.flexibility_cls.scripts.config import RES_MINUTES, S_RATED_KVA, P_LIMIT_KW, THETA_MAX

PALETTE = {
    "buildings": "#3498db",
    "evs_mean": "#e67e22",
    "evs_worst": "#d35400",
    "soft_cls_contract": "#2ecc71",
    "hard_cls_expected": "#9b59b6",
    "thermal_limit": "#c0392b"
}

def main():
    data_dir = ROOT / "projects/flexibility_cls/outputs/data"
    out_dir = ROOT / "projects/flexibility_cls/outputs/figures/04_stage3_market_clearing"
    out_dir.mkdir(parents=True, exist_ok=True)

    df_base = pd.read_parquet(data_dir / "substation_baseline_mc.parquet")
    df_ev = pd.read_parquet(data_dir / "substation_ev_capability_mc.parquet")

    p_base_kw_mean = df_base.mean(axis=1).values * 1000.0
    p_base_kw_std = df_base.std(axis=1).values * 1000.0
    p_ev_kw_mean = df_ev.mean(axis=1).values * 1000.0 * (40.0 / 30.0)
    p_ev_kw_std = df_ev.std(axis=1).values * 1000.0 * (40.0 / 30.0)

    tmy = download_tmy()
    cold_day = select_peak_load_day(tmy, duration_hours=28)
    t_out_trace = cold_day["temp_air"].resample(f"{RES_MINUTES}min").interpolate().values

    from gridalyn.datagen.grid.transformer_thermal import TransformerThermalModel
    thermal_model = TransformerThermalModel(theta_max=THETA_MAX, s_rated_kva=S_RATED_KVA)
    network = MVNetwork(thermal_model=thermal_model, p_rated_kw=P_LIMIT_KW)
    dt_h = RES_MINUTES / 60.0
    dispatcher = DSODispatcher(network=network, dt_man_h=dt_h, epsilon=0.05, stochastic_failure_rate=0.05)
    market_engine = MarketSimulationEngine(network=network, dispatcher=dispatcher)

    df_res = market_engine.run(
        p_base_kw_mean=p_base_kw_mean,
        p_base_kw_std=p_base_kw_std,
        p_ev_kw_mean=p_ev_kw_mean,
        p_ev_kw_std=p_ev_kw_std,
        t_out_trace_c=t_out_trace,
        dt_man_h=dt_h,
        n_total_blocks=160,
        participation_rate=0.30,
        epsilon=0.05,
        is_profiled=True,
        market_resolution_h=0.5
    )

    n_steps = len(p_base_kw_mean)
    t_hours = np.arange(n_steps) * (RES_MINUTES / 60)
    p_tot_mean = df_res["p_tot_mean_kw"].values / 1000.0
    p_tot_std = df_res["p_tot_std_kw"].values / 1000.0

    p_limit = np.zeros(len(t_out_trace))
    for t in range(len(t_out_trace)):
        p_limit[t] = thermal_model.max_load_for_temp(t_out_trace[t]) / 1000.0

    contracted_soft_mw = df_res["contracted_soft_kw"].values / 1000.0
    expected_hard_mw = df_res["hard_cls_kw"].values / 1000.0

    from scipy.stats import norm
    z_score = norm.ppf(1 - 0.05)
    p_worst = p_tot_mean + z_score * p_tot_std

    # ── Build individual MC trajectories (S4: 40% EV) ───────────────────────────
    # Data is in MW at substation level; scale EV from 30% to 40%
    n_reals = df_base.shape[1]
    base_vals = df_base.values[:n_steps, :]      # (n_steps, 30) MW
    ev_vals   = df_ev.values[:n_steps, :]         # (n_steps, 30) MW
    s4_mc     = base_vals + ev_vals * (40.0/30.0) # (n_steps, 30) MW — individual trajectories

    # ── Plot ────────────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(14, 7))

    # Individual MC trajectories (thin, translucent)
    for i in range(n_reals):
        label = r"MC Realizations ($n=30$, S4)" if i == 0 else None
        ax.plot(t_hours, s4_mc[:, i], color="#E67E22", alpha=0.18,
                linewidth=0.5, zorder=2, label=label)

    # Mean (μ) and worst-case envelope (μ + Z·σ) — keep for CLS reference
    ax.plot(t_hours, p_tot_mean, color='black', lw=2.0, zorder=5,
            label=r"Expected Unmanaged Load ($\mu$)")
    ax.plot(t_hours, p_worst, color=PALETTE["evs_worst"], lw=2.0, ls='--', zorder=5,
            label=r"95th Pct. Worst-Case Envelope ($\mu + Z \cdot \sigma$)")

    # Dynamic thermal limit
    ax.plot(t_hours, p_limit, color=PALETTE["thermal_limit"], lw=3, ls='-', zorder=6,
            label=r"Dynamic Thermal Limit ($\theta_H$)")

    # ── Flexibility surfaces (unchanged) ────────────────────────────────────────
    # Expected Activations for visualization
    expected_soft_act_mw = np.minimum(contracted_soft_mw, np.maximum(0, p_worst - p_limit))
    expected_hard_act_mw = np.maximum(0, p_worst - p_limit - expected_soft_act_mw)

    # 1. Fill Expected Soft-CLS Activation
    ax.fill_between(t_hours, p_worst - expected_soft_act_mw, p_worst, where=(expected_soft_act_mw > 0),
                    color=PALETTE["soft_cls_contract"], alpha=0.8, label="Soft-CLS: Firm Contracted Capacity",
                    zorder=7)

    # 2. Fill Expected Hard-CLS Activation
    ax.fill_between(t_hours, p_worst - expected_soft_act_mw - expected_hard_act_mw, p_worst - expected_soft_act_mw, where=(expected_hard_act_mw > 0),
                    color=PALETTE["hard_cls_expected"], alpha=0.6, label="Hard-CLS: Expected Interruptible Recourse",
                    zorder=7)

    # 3. Expected Post-Congestion Rebound (energy-conserving with the green area)
    # Physical principle: all curtailed energy must eventually return as rebound.
    # E_rebound = E_curtailment = ∫ expected_soft_act · dt
    #
    # The engine's rebound_kw is from the mean scenario, but the green area shows
    # the expected curtailment against the worst-case envelope (p_worst).
    # For DA planning consistency, we compute the expected rebound analytically:
    # accumulate deficit from the green area, then drain it post-congestion using
    # P-controller dynamics clamped by the available thermal margin.
    dt_h = RES_MINUTES / 60.0
    K_P = 2.0   # P-controller gain [kW/kWh] — matches BuildingAggregator.K_P_REBOUND
    OVERSIZE = 1.30  # HVAC headroom factor — matches BuildingAggregator.HEATING_OVERSIZE

    accumulated_deficit_mwh = 0.0
    drawn_rebound = np.zeros(len(t_hours))

    for t in range(len(t_hours)):
        # Accumulate deficit from the planned curtailment (green area)
        accumulated_deficit_mwh += expected_soft_act_mw[t] * dt_h

        # When not being curtailed, recover via P-controller
        if expected_soft_act_mw[t] < 0.001 and accumulated_deficit_mwh > 1e-6:
            # P-controller drive (scaled to MW)
            p_drive = K_P * accumulated_deficit_mwh  # MW

            # Physical headroom: managed load can only rise up to thermal limit
            p_managed_t = p_worst[t] - expected_soft_act_mw[t] - expected_hard_act_mw[t]
            available_margin = max(0, p_limit[t] - p_managed_t)

            # Also cap by HVAC headroom above baseline
            hvac_headroom = p_tot_mean[t] * (OVERSIZE - 1.0)

            # Take the binding constraint
            rebound_power = min(p_drive, available_margin, hvac_headroom)

            # Don't drain more than remaining deficit
            max_drain = accumulated_deficit_mwh / dt_h
            rebound_power = min(rebound_power, max_drain)

            drawn_rebound[t] = rebound_power
            accumulated_deficit_mwh = max(0, accumulated_deficit_mwh - rebound_power * dt_h)

    if np.max(drawn_rebound) > 0:
        ax.fill_between(t_hours, p_tot_mean, p_tot_mean + drawn_rebound,
                        where=(drawn_rebound > 0.001),
                        color="#D9534F", alpha=0.8, hatch='\\\\', label="Expected Post-Congestion Rebound",
                        zorder=7)


    ax.set_ylabel("Substation Power Demand [MW]", fontsize=14)

    # Title removed — provided by LaTeX caption in paper

    ax.set_xlim(0, 28)
    y_lo = min(np.min(p_tot_mean), np.min(s4_mc)) * 0.92
    y_hi = max(np.max(p_worst), np.max(p_limit), np.max(s4_mc)) * 1.08
    ax.set_ylim(y_lo, y_hi)
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
    ax.legend(loc="upper left", fontsize=11, framealpha=0.95)
    plt.tight_layout()

    out_path = out_dir / "plot_14b_stage_1_profiled.png"
    out_pdf_path = out_path.with_suffix(".pdf")
    fig.savefig(out_pdf_path, bbox_inches="tight")
    print(f"Saved PDF to {out_pdf_path}")

    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    print(f"Saved to {out_path}")

if __name__ == "__main__":
    main()
