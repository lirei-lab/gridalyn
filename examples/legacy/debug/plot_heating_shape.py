import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from gridalyn.datagen.data.weather import download_tmy, select_cold_day

def main():
    print("1. Loading HQ Data...")
    df_m = pd.read_hdf('datasets/hq/meteo.h5')
    df_c = pd.read_hdf('datasets/hq/consumption.h5') / 1000.0
    df_h = pd.read_hdf('datasets/hq/heating.h5') / 1000.0

    daily_min_temp = df_m['DryBulb'].resample('D').min()
    cold_days = daily_min_temp.sort_values().head(5).index

    hq_total_profiles = []
    hq_heat_profiles = []
    
    avg_home_kw_total = df_c.sum(axis=1) / 1000.0
    avg_home_kw_heat = df_h.sum(axis=1) / 1000.0
    
    for d in cold_days:
        try:
            day_str = d.strftime('%Y-%m-%d')
            hq_total_profiles.append(avg_home_kw_total.loc[day_str].groupby(avg_home_kw_total.loc[day_str].index.hour).mean().values)
            hq_heat_profiles.append(avg_home_kw_heat.loc[day_str].groupby(avg_home_kw_heat.loc[day_str].index.hour).mean().values)
        except Exception as e:
            print(f"Skipping {d}: {e}")
            pass
            
    hq_avg_total = np.mean(hq_total_profiles, axis=0)
    hq_avg_heat = np.mean(hq_heat_profiles, axis=0)
    hq_avg_bg = hq_avg_total - hq_avg_heat

    print("2. Simulating Gridalyn Data via Parametric ARX...")
    tmy = download_tmy()
    cold_day = select_cold_day(tmy)
    time_idx = pd.date_range("2024-01-01 00:00:00", periods=len(cold_day["temp_air"]), freq="min")
    temperature_15m = pd.Series(cold_day["temp_air"].values, index=time_idx).resample('15min').mean()

    n_houses = 3235
    
    from gridalyn.simulators.agents.unmanaged_loads import ParametricArxGenerator
    gen = ParametricArxGenerator()
    gen.load()

    bld_heat_kw, bld_bg_kw = gen.generate(temperature_15m, n_houses=n_houses)

    # Convert 15-minute generation into hourly averages for this specific plot
    total_agg = np.mean(bld_heat_kw + bld_bg_kw, axis=1)
    heat_agg = np.mean(bld_heat_kw, axis=1)
    
    synt_hourly = pd.DataFrame({
        'heat': heat_agg,
        'bg': total_agg - heat_agg,
        'hour': np.repeat(np.arange(24), 4)
    }).groupby('hour').mean()

    print("3. Generating Plot...")
    fig, ax = plt.subplots(figsize=(10, 6))
    hours_x = np.arange(24)

    # Plot Gridalyn Separated (Solid Lines)
    ax.plot(hours_x, synt_hourly['heat'], label="Gridalyn: Heating Load (-25°C)", color='red', linewidth=3)
    ax.plot(hours_x, synt_hourly['bg'], label="Gridalyn: Non-Heating Load", color='blue', linewidth=3)
    ax.plot(hours_x, synt_hourly['heat'] + synt_hourly['bg'], label="Gridalyn: Total Active Load", color='orange', linewidth=2, linestyle=':')

    # Plot HQ Extracted (Dashed Lines)
    ax.plot(hours_x, hq_avg_heat, label="HQ: Extracted Heating Load (~-23°C)", color='darkred', linestyle='--', linewidth=3)
    ax.plot(hours_x, hq_avg_bg, label="HQ: Extracted Non-Heating Load", color='navy', linestyle='--', linewidth=3)
    
    # Fill background for Gridalyn
    ax.fill_between(hours_x, 0, synt_hourly['bg'], alpha=0.15, color='blue')
    ax.fill_between(hours_x, synt_hourly['bg'], synt_hourly['heat'] + synt_hourly['bg'], alpha=0.15, color='red')

    ax.set_title("Stochastic Demands: True Hydro-Québec Data vs Geopower Digital Twin", fontsize=14, fontweight='bold')
    ax.set_xlabel("Hour of Day", fontsize=12)
    ax.set_ylabel("Demand Profile (kW / home)", fontsize=12)
    ax.set_xticks(np.arange(0, 24, 2))
    ax.grid(True, linestyle='-', alpha=0.3)
    ax.legend(loc='lower left', bbox_to_anchor=(1.02, 0.5), fontsize=10)

    plt.tight_layout()
    out_dir = "/home/lirei-lenovo/.gemini/antigravity/brain/f0b96534-c013-4c81-8cdb-4caa2e2e3fbd"
    out_file = os.path.join(out_dir, "hq_heating_split_v2.png")
    plt.savefig(out_file, dpi=200, bbox_inches='tight')
    print(f"[{out_file}] successfully written!")

if __name__ == "__main__":
    main()
