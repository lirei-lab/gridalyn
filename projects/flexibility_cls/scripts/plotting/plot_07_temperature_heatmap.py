import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import scipy.stats as stats
from pathlib import Path

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.datagen.grid.transformer_thermal import TransformerThermalModel
from gridalyn.datagen.data.weather import download_tmy, select_cold_day

def main():
    print("="*60)
    print("  Generating Temperature Probability Density Heatmap...")
    print("="*60)
    
    data_dir = ROOT / "projects/flexibility_cls/outputs/data"
    fig_dir = ROOT / "projects/flexibility_cls/outputs/figures/03_stage2_thermal_screening"
    fig_dir.mkdir(parents=True, exist_ok=True)
    
    df_ts = pd.read_parquet(data_dir / "market_dispatch_timeseries.parquet")
    t_hours = df_ts["t_hours"].values
    n_steps = len(t_hours)
    
    # Unmanaged
    mu_unmanaged = df_ts["p_baseline_mean_mw"].values + df_ts["p_ev_mean_mw"].values
    sigma = df_ts["p_tot_std_mw"].values
    
    # Managed
    p_soft = df_ts["p_soft_cls_mw"].values
    p_hard = df_ts["p_hard_cls_mw"].values
    mu_managed = mu_unmanaged - p_soft - p_hard
    
    # Get weather
    try:
        tmy = download_tmy()
        cold = select_cold_day(tmy)
        t_out = cold["temp_air"].resample("5min").mean().values
        if len(t_out) < n_steps:
            t_out = np.pad(t_out, (0, n_steps - len(t_out)), mode='edge')
        t_out = t_out[:n_steps]
    except Exception:
        t_out = np.full(n_steps, -22.5) # fallback
        
    from projects.flexibility_cls.scripts.config import S_RATED_KVA, THETA_MAX
    thermal_model = TransformerThermalModel(s_rated_kva=S_RATED_KVA, theta_max=THETA_MAX)
    
    # Load actual MC traces for realistic thermal variance
    from projects.flexibility_cls.scripts.data_api import get_baseline_building_load_all
    try:
        bldg_realizations = get_baseline_building_load_all()[:, :n_steps] # kW
    except Exception as e:
        print(f"Warning: could not load building realizations ({e}). Generating correlated fallback.")
        N_TRACES = 1000
        bldg_realizations = np.zeros((N_TRACES, n_steps))
        base_mean = df_ts["p_baseline_mean_mw"].values * 1000
        for i in range(N_TRACES):
            # simplistic AR(1) to avoid white-noise cancellation
            noise = np.zeros(n_steps)
            noise[0] = np.random.normal(0, sigma[0]*1000)
            for t in range(1, n_steps):
                noise[t] = 0.95 * noise[t-1] + np.random.normal(0, sigma[t]*1000 * 0.3)
            bldg_realizations[i] = base_mean + noise
            
    N_TRACES = min(1000, bldg_realizations.shape[0])
    
    theta_unmanaged_traces = np.zeros((N_TRACES, n_steps))
    theta_managed_traces = np.zeros((N_TRACES, n_steps))
    
    p_ev_kw = df_ts["p_ev_mean_mw"].values * 1000
    p_flex_kw = (p_soft + p_hard) * 1000
    
    # Calculate DSO activation threshold
    # P_worst is the 95th percentile used during procurement
    import scipy.stats as stats
    z_score = stats.norm.ppf(0.95)
    p_worst_kw = (mu_unmanaged + z_score * sigma) * 1000
    p_threshold_kw = p_worst_kw - p_flex_kw
    
    print(f"  Simulating {N_TRACES} traces through thermal model...")
    for i in range(N_TRACES):
        # unmanaged = building + EV
        p_unmanaged_trace = bldg_realizations[i] + p_ev_kw
        
        # managed: DSO only activates flexibility when load exceeds threshold, capped at procured flex
        curtailment = np.clip(p_unmanaged_trace - p_threshold_kw, 0, p_flex_kw)
        p_managed_trace = p_unmanaged_trace - curtailment
        
        theta_unmanaged_traces[i, :] = thermal_model.simulate_profile(p_unmanaged_trace, t_out, dt_min=5.0)
        theta_managed_traces[i, :] = thermal_model.simulate_profile(p_managed_trace, t_out, dt_min=5.0)
        
    # Create 2D grid for Temperature
    y_min = max(0, np.min(theta_managed_traces) - 5)
    y_max = np.max(theta_unmanaged_traces) + 10
    Y = np.linspace(y_min, y_max, 200)
    X = t_hours
    
    Z_unmanaged = np.zeros((len(Y), len(X)))
    Z_managed = np.zeros((len(Y), len(X)))
    
    # Calculate density for each timestep using KDE
    for t in range(n_steps):
        # Add a tiny bit of noise if all traces are identical (e.g. early morning)
        traces_un = theta_unmanaged_traces[:, t]
        traces_mn = theta_managed_traces[:, t]
        if np.std(traces_un) < 1e-4: traces_un += np.random.normal(0, 1e-3, N_TRACES)
        if np.std(traces_mn) < 1e-4: traces_mn += np.random.normal(0, 1e-3, N_TRACES)
        
        kde_unmanaged = stats.gaussian_kde(traces_un)
        kde_managed = stats.gaussian_kde(traces_mn)
        
        Z_unmanaged[:, t] = kde_unmanaged(Y)
        Z_managed[:, t] = kde_managed(Y)
        
    fig, axes = plt.subplots(1, 2, figsize=(16, 6), sharey=True, constrained_layout=True)
    cmap = "Oranges"
    
    limit = np.full(n_steps, THETA_MAX)
    
    # Panel 1: Unmanaged
    ax1 = axes[0]
    c1 = ax1.pcolormesh(X, Y, Z_unmanaged, shading='auto', cmap=cmap, vmax=np.max(Z_unmanaged)*0.8)
    ax1.plot(X, limit, color="red", lw=2, ls="--", label=f"Thermal Limit ({THETA_MAX} °C)")
    ax1.plot(X, np.mean(theta_unmanaged_traces, axis=0), color="black", lw=1.5, label="Expected Mean Temp")
    
    # Overlay risk
    Z_risk = np.copy(Z_unmanaged)
    for i in range(len(X)):
        Z_risk[Y < limit[i], i] = np.nan
        Z_risk[Z_risk < 0.01] = np.nan
        
    ax1.pcolormesh(X, Y, Z_risk, shading='auto', cmap="Reds", alpha=0.6)
    
    ax1.set_title("A) Unmanaged Temperature Probability Density", fontsize=14, pad=15)
    ax1.set_ylabel("Hottest-Spot Temperature (°C)", fontsize=12)
    ax1.set_xlabel("Hour of Day", fontsize=12)
    ax1.legend(loc="upper left")
    
    # Panel 2: Managed
    ax2 = axes[1]
    c2 = ax2.pcolormesh(X, Y, Z_managed, shading='auto', cmap=cmap, vmax=np.max(Z_unmanaged)*0.8)
    ax2.plot(X, limit, color="red", lw=2, ls="--", label=f"Thermal Limit ({THETA_MAX} °C)")
    ax2.plot(X, np.mean(theta_managed_traces, axis=0), color="black", lw=1.5, label="Expected Mean Temp")
    
    ax2.set_title("B) Managed Temperature Probability Density", fontsize=14, pad=15)
    ax2.set_xlabel("Hour of Day", fontsize=12)
    ax2.legend(loc="upper left")
    
    for ax in axes:
        ax.set_xlim(0, 26)
        ax.set_xticks(range(0, 27, 4))
        ax.set_xticklabels([f"{h%24:02d}:00" for h in range(0, 27, 4)], rotation=30, ha="right")
        ax.grid(True, alpha=0.3, color="white", lw=0.5)
        ax.set_ylim(min(20, y_min), max(130, y_max))
        
    # Colorbar
    cbar = fig.colorbar(c1, ax=axes, orientation='vertical', fraction=0.02, pad=0.02)
    cbar.set_label("Probability Density", fontsize=12)
    
    output_path = fig_dir / "temperature_probability_heatmap.png"
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    fig.savefig(fig_dir / "temperature_probability_heatmap.pdf", dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> Saved Temperature PDF Heatmap to {output_path}\n")

if __name__ == "__main__":
    main()
