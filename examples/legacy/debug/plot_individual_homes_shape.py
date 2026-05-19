import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from gridalyn.simulators.agents.fleet import make_buildings, simulate_buildings
from gridalyn.datagen.data.weather import download_tmy, select_cold_day

def main():
    print("1. Loading HQ Individual Data...")
    df_m = pd.read_hdf('datasets/hq/meteo.h5')
    df_c = pd.read_hdf('datasets/hq/consumption.h5') / 1000.0

    # Pick the absolute coldest day in HQ dataset
    daily_min_temp = df_m['DryBulb'].resample('D').min()
    coldest_day_str = daily_min_temp.idxmin().strftime('%Y-%m-%d')
    print(f"Coldest real HQ day: {coldest_day_str}")

    # Extract exactly 3 random homes for that day
    hq_home_1 = df_c['0'].loc[coldest_day_str]
    hq_home_2 = df_c['125'].loc[coldest_day_str]
    hq_home_3 = df_c['555'].loc[coldest_day_str]

    # Convert to hourly for smoother plotting if needed, but 15-min is better for spikiness
    # The HQ data is 15-minute resolution
    hq_time_axis = np.linspace(0, 24, len(hq_home_1))

    print("2. Simulating Gridalyn Individual Data...")
    tmy = download_tmy()
    cold_day = select_cold_day(tmy)
    time_idx = pd.date_range("2024-01-01 00:00:00", periods=len(cold_day["temp_air"]), freq="min")
    temperature = pd.Series(cold_day["temp_air"].values, index=time_idx)

    # Make exactly 3 buildings
    buildings = make_buildings(3, seed=99)
    bld_results = simulate_buildings(buildings, temperature)

    # Extract their Total 1-min traces
    bld_keys = list(bld_results.keys())
    synt_home_1 = bld_results[bld_keys[0]]["p_total_kw"].values
    synt_home_2 = bld_results[bld_keys[1]]["p_total_kw"].values
    synt_home_3 = bld_results[bld_keys[2]]["p_total_kw"].values

    # Resample to 15-min to match HQ vis exactly
    synt_home_1_15m = np.mean(synt_home_1.reshape(-1, 15), axis=1)
    synt_home_2_15m = np.mean(synt_home_2.reshape(-1, 15), axis=1)
    synt_home_3_15m = np.mean(synt_home_3.reshape(-1, 15), axis=1)
    synt_time_axis = np.linspace(0, 24, len(synt_home_1_15m))

    print("3. Generating Individual Plots...")
    fig, axes = plt.subplots(3, 2, figsize=(14, 10), sharex=True, sharey=True)

    # HQ Plots (Left Column)
    axes[0, 0].plot(hq_time_axis, hq_home_1.values, color='black', linewidth=1.5)
    axes[0, 0].set_title(f"HQ Home A (Real 15-min Trace)", fontsize=11, fontweight='bold')
    
    axes[1, 0].plot(hq_time_axis, hq_home_2.values, color='black', linewidth=1.5)
    axes[1, 0].set_title(f"HQ Home B (Real 15-min Trace)", fontsize=11, fontweight='bold')
    
    axes[2, 0].plot(hq_time_axis, hq_home_3.values, color='black', linewidth=1.5)
    axes[2, 0].set_title(f"HQ Home C (Real 15-min Trace)", fontsize=11, fontweight='bold')
    axes[2, 0].set_xlabel("Hour of Day", fontsize=12)

    # Gridalyn Plots (Right Column)
    axes[0, 1].plot(synt_time_axis, synt_home_1_15m, color='purple', linewidth=1.5)
    axes[0, 1].set_title(f"Gridalyn Home X (Simulated 15-min Trace)", fontsize=11, fontweight='bold')
    
    axes[1, 1].plot(synt_time_axis, synt_home_2_15m, color='purple', linewidth=1.5)
    axes[1, 1].set_title(f"Gridalyn Home Y (Simulated 15-min Trace)", fontsize=11, fontweight='bold')
    
    axes[2, 1].plot(synt_time_axis, synt_home_3_15m, color='purple', linewidth=1.5)
    axes[2, 1].set_title(f"Gridalyn Home Z (Simulated 15-min Trace)", fontsize=11, fontweight='bold')
    axes[2, 1].set_xlabel("Hour of Day", fontsize=12)

    for i in range(3):
        for j in range(2):
            axes[i, j].set_ylabel("Power (kW)", fontsize=10)
            axes[i, j].set_xticks(np.arange(0, 25, 4))
            axes[i, j].grid(True, linestyle='--', alpha=0.5)

    fig.suptitle("High-Frequency Volatility: Real vs Synthesized Individual Dwellings", fontsize=16, fontweight='bold')

    plt.tight_layout()
    out_dir = "/home/lirei-lenovo/.gemini/antigravity/brain/f0b96534-c013-4c81-8cdb-4caa2e2e3fbd"
    out_file = os.path.join(out_dir, "hq_individual_homes_comparison.png")
    plt.savefig(out_file, dpi=200, bbox_inches='tight')
    print(f"[{out_file}] successfully written!")

if __name__ == "__main__":
    main()
