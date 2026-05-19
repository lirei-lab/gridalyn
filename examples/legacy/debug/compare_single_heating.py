import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

from gridalyn.simulators.agents.buildings import Building

HEATING_H5 = "datasets/hq/heating.h5"
METEO_H5 = "datasets/hq/meteo.h5"
OUTPUT_IMG = "datasets/hq/single_heating_comparison.png"

def main():
    print("1. Loading Hydro-Québec Data...")
    df_h = pd.read_hdf(HEATING_H5)
    df_m = pd.read_hdf(METEO_H5)
    
    # Grab first 3 days
    start_dt = df_h.index[0]
    end_dt = start_dt + pd.Timedelta(days=3)
    
    # Pick Building 0
    hq_house_w = df_h.loc[start_dt:end_dt].iloc[:, 0]
    hq_house_kw = hq_house_w / 1000.0
    
    # Weather
    weather_h = df_m[['DryBulb']].resample('h').mean().interpolate()
    # Interpolate to 15 min to match HQ
    weather_15 = weather_h.resample('15min').interpolate().loc[hq_house_kw.index]

    print("2. Simulating Gridalyn Equivalent (1 Building)...")
    b = Building(unit_id="B_0")
    
    sim_mins = 3 * 24 * 60
    synth_heat = np.zeros(sim_mins)
    synth_temp = np.zeros(sim_mins)
    
    temp_min_array = np.zeros(sim_mins)
    for h in range(3 * 24):
        h_dt = start_dt + pd.Timedelta(hours=h)
        if h_dt in weather_h.index:
            t = weather_h.loc[h_dt, 'DryBulb']
        else:
            t = weather_h['DryBulb'].mean()
        temp_min_array[h*60 : (h+1)*60] = t

    for m in range(sim_mins):
        t_out = temp_min_array[m]
        res = b.step(t_out=t_out, minute_of_day=m % 1440)
        synth_heat[m] = res['p_heat_kw']
        synth_temp[m] = res['T_in_C']

    # Convert synth to DataFrame for plotting
    synth_df = pd.DataFrame({
        'heat_kw': synth_heat,
        'T_in': synth_temp
    }, index=pd.date_range(start=start_dt, periods=sim_mins, freq='min'))
    
    print("3. Plotting...")
    fig, axes = plt.subplots(3, 1, figsize=(14, 12), sharex=True)
    
    # Plot HQ Single House Heating
    ax = axes[0]
    ax.plot(hq_house_kw.index, hq_house_kw, color='green', label="HQ House 0 Heating (kW)")
    ax.set_title("Hydro-Québec Single House Heating Profile (15-min res)", fontsize=12, fontweight='bold')
    ax.set_ylabel("Heating Power (kW)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc='upper right')

    # Plot Gridalyn Single House Heating
    ax = axes[1]
    ax.plot(synth_df.index, synth_df['heat_kw'], color='red', label="Gridalyn House Heating (kW)")
    ax.set_title("Gridalyn Gridalyn Single House Heating Profile (1-min res) [CURRENT BANG-BANG]", fontsize=12, fontweight='bold')
    ax.set_ylabel("Heating Power (kW)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc='upper right')
    
    # Optional Plot T_in to see the thermostatic bounds
    ax = axes[2]
    ax.plot(weather_15.index, weather_15['DryBulb'], color='gray', linestyle='--', label="Outdoor Temp (°C)")
    ax.plot(synth_df.index, synth_df['T_in'], color='magenta', label="Gridalyn Indoor Temp (°C)")
    ax.axhline(y=21.0, color='black', linestyle=':', alpha=0.5, label="Setpoint 21°C")
    ax.set_title("Temperatures", fontsize=12, fontweight='bold')
    ax.set_ylabel("Temp (°C)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc='upper right')

    plt.tight_layout()
    plt.savefig(OUTPUT_IMG, dpi=200, bbox_inches='tight')
    print(f"Saved: {OUTPUT_IMG}")

if __name__ == "__main__":
    main()
