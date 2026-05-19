import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from tqdm import tqdm

from gridalyn.simulators.agents.buildings import Building

CONSUMPTION_H5 = "datasets/hq/consumption.h5"
METEO_H5 = "datasets/hq/meteo.h5"
OUTPUT_IMG = "datasets/hq/hq_comparison.png"
NUM_BUILDINGS = 1000
SIM_DAYS = 7

def main():
    print("1. Loading Hydro-Québec Data...")
    
    # -- Electric --
    print("   Reading consumption.h5...")
    df_c = pd.read_hdf(CONSUMPTION_H5)
    
    # Define time window
    start_dt = df_c.index[0]
    end_dt = start_dt + pd.Timedelta(days=SIM_DAYS)
    
    # Filter 7 days roughly, convert Watts to kW
    df_c_week = df_c.loc[start_dt:end_dt] / 1000.0
    # Aggregate all 1000 houses per 15 min -> then hourly mean
    real_agg_kw = df_c_week.sum(axis=1).resample('h').mean()
    
    # -- Weather --
    print("   Reading meteo.h5...")
    df_m = pd.read_hdf(METEO_H5)
    # DryBulb is the temperature in C
    weather_h = df_m[['DryBulb']].resample('h').mean().interpolate()
    # Align the weather to the consumption window
    weather_h = weather_h.loc[real_agg_kw.index]
    
    # Merge real data
    real_merged = pd.concat([real_agg_kw.rename('load_kw'), weather_h['DryBulb'].rename('temp_C')], axis=1).dropna()

    print(f"2. Simulating Gridalyn Equivalent ({NUM_BUILDINGS} Buildings)...")
    buildings = [Building(unit_id=f"B_{i}") for i in range(NUM_BUILDINGS)]
    
    # Simulate minute by minute
    total_minutes = SIM_DAYS * 24 * 60
    
    synth_total = np.zeros(total_minutes)
    synth_heat = np.zeros(total_minutes)
    synth_base = np.zeros(total_minutes)
    
    temp_min_array = np.zeros(total_minutes)
    
    for h in range(SIM_DAYS * 24):
        h_dt = start_dt + pd.Timedelta(hours=h)
        if h_dt in weather_h.index:
            t = weather_h.loc[h_dt, 'DryBulb']
        else:
            t = weather_h['DryBulb'].mean()
        temp_min_array[h*60 : (h+1)*60] = t

    for m in tqdm(range(total_minutes), desc="Simulating minutes"):
        t_out = temp_min_array[m]
        minute_of_day = m % 1440
        
        m_tot, m_heat, m_base = 0.0, 0.0, 0.0
        for b in buildings:
            res = b.step(t_out=t_out, minute_of_day=minute_of_day)
            m_tot += res['p_total_kw']
            m_heat += res['p_heat_kw']
            m_base += res['p_bg_kw']
        
        synth_total[m] = m_tot
        synth_heat[m] = m_heat
        synth_base[m] = m_base

    # Aggregate synthetic to hourly
    synth_df = pd.DataFrame({
        'total_kw': synth_total,
        'heat_kw': synth_heat,
        'base_kw': synth_base
    }, index=pd.date_range(start=start_dt, periods=total_minutes, freq='min'))
    
    synth_h = synth_df.resample('h').mean()
    synth_merged = synth_h.copy()
    synth_merged['temp_C'] = temp_min_array[::60][:len(synth_h)]

    print("3. Generating Comparison Verification Report...")
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    
    # PLOT 1: Real HQ Data
    ax = axes[0]
    sns.scatterplot(data=real_merged, x='temp_C', y='load_kw', ax=ax, alpha=0.7, color='black', label="HQ Total Load (1000 Houses)")
    
    m_real, b_real = np.polyfit(real_merged['temp_C'], real_merged['load_kw'], 1)
    ax.plot(real_merged['temp_C'], m_real * real_merged['temp_C'] + b_real, color='red', linestyle='--', 
            label=f"HQ Heating Coef: {m_real:.2f} kW/°C")
    
    ax.invert_xaxis()  # Colder on the right
    ax.set_title("Hydro-Québec Simulated Data (1000 Houses)", fontsize=12, fontweight='bold')
    ax.set_xlabel("Outdoor Temperature (°C)")
    ax.set_ylabel("Aggregate Power (kW)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc='lower left')

    max_x = max(real_merged['load_kw'].max(), synth_merged['total_kw'].max()) * 1.1

    ax.set_ylim(0, max_x)

    # PLOT 2: Gridalyn Equivalent (1000 Buildings)
    ax = axes[1]
    sns.scatterplot(data=synth_merged, x='temp_C', y='base_kw', ax=ax, alpha=0.4, color='blue', label="Gridalyn Non-Heat Baseline")
    sns.scatterplot(data=synth_merged, x='temp_C', y='total_kw', ax=ax, alpha=0.7, color='darkorange', label="Gridalyn Total Load (Base + Heat)")
    
    m_syn, b_syn = np.polyfit(synth_merged['temp_C'], synth_merged['total_kw'], 1)
    ax.plot(synth_merged['temp_C'], m_syn * synth_merged['temp_C'] + b_syn, color='red', linestyle='--', 
            label=f"Gridalyn Heating Coef: {m_syn:.2f} kW/°C")

    ax.invert_xaxis()
    ax.set_title("Gridalyn RC Model (1000 Buildings)", fontsize=12, fontweight='bold')
    ax.set_xlabel("Outdoor Temperature (°C)")
    ax.set_ylabel("Aggregate Power (kW)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc='lower left')
    ax.set_ylim(0, max_x)

    plt.suptitle("Stochastic Heating Physics Verification: Hydro-Québec Data vs Gridalyn Engine", fontsize=15, fontweight='bold')
    plt.tight_layout()
    plt.savefig(OUTPUT_IMG, dpi=200, bbox_inches='tight')
    
    print("\n[VERIFICATION RESULTS]")
    print(f"Hydro-Québec Aggregate Heating Slope: {m_real:.2f} kW/°C")
    print(f"Gridalyn Aggregate Heating Slope:     {m_syn:.2f} kW/°C")
    print(f"\nSaved image to: {OUTPUT_IMG}")

if __name__ == "__main__":
    main()
