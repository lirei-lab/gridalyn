import os
import glob
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from tqdm import tqdm

from gridalyn.simulators.agents.buildings import Building

ELECTRIC_DIR = "datasets/umass_data/apartment/2016"
WEATHER_FILE = "datasets/umass_data/apartment-weather/apartment2016.csv"
OUTPUT_IMG = "datasets/umass_data/heating_comparison.png"

def main():
    print("1. Loading UMass Data...")
    # -- Weather --
    weather = pd.read_csv(WEATHER_FILE)
    weather['datetime'] = pd.to_datetime(weather['time'], unit='s', utc=True).dt.tz_convert('EST').dt.tz_localize(None)
    weather.set_index('datetime', inplace=True)
    # Convert F to C
    weather['temp_C'] = (weather['temperature'] - 32.0) * (5.0 / 9.0)
    weather_h = weather[['temp_C']].resample('h').mean().interpolate()

    # -- Electric --
    csv_files = glob.glob(os.path.join(ELECTRIC_DIR, "Apt*_2016.csv"))[:100]
    start_date = '2016-01-15'
    end_date = '2016-01-21'

    apt_data = {}
    for i, file in enumerate(csv_files):
        df = pd.read_csv(file, header=None, names=['datetime', 'kw'])
        df['datetime'] = pd.to_datetime(df['datetime'])
        df.set_index('datetime', inplace=True)
        df = df.loc[start_date:end_date]
        if not df.empty:
            apt_data[f'Apt_{i}'] = df['kw']

    df_all_min = pd.DataFrame(apt_data).fillna(0)
    real_agg_kw = df_all_min.sum(axis=1).resample('h').mean()
    
    # Merge real data
    real_merged = pd.concat([real_agg_kw.rename('load_kw'), weather_h['temp_C']], axis=1).dropna()
    real_merged = real_merged.loc[start_date:end_date]

    print("2. Simulating Gridalyn Equivalent (100 Buildings)...")
    # Initialize 100 custom buildings (realistic distribution)
    # Using the RC params from our simulation
    buildings = [Building(unit_id=f"B_{i}") for i in range(100)]
    
    # Extract the exact temperature array to force into our synthetic model
    # We simulate minute by minute for the whole 7 days
    num_days = 7
    total_minutes = num_days * 24 * 60
    
    synth_total = np.zeros(total_minutes)
    synth_heat = np.zeros(total_minutes)
    synth_base = np.zeros(total_minutes)
    
    # Fast array of hourly temps mapped to minutes
    # using start_date forward
    start_dt = pd.to_datetime(start_date)
    temp_min_array = np.zeros(total_minutes)
    
    # prep minute temperatures safely
    for h in range(num_days * 24):
        h_dt = start_dt + pd.Timedelta(hours=h)
        if h_dt in weather_h.index:
            t = weather_h.loc[h_dt, 'temp_C']
        else:
            t = weather_h['temp_C'].mean() # fallback
        temp_min_array[h*60 : (h+1)*60] = t

    # Run Simulation
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

    # Aggregate synthetic to hourly exactly like UMass
    synth_df = pd.DataFrame({
        'total_kw': synth_total,
        'heat_kw': synth_heat,
        'base_kw': synth_base
    }, index=pd.date_range(start=start_date, periods=total_minutes, freq='min'))
    
    synth_h = synth_df.resample('h').mean()
    # Align temps
    synth_merged = synth_h.copy()
    synth_merged['temp_C'] = temp_min_array[::60][:len(synth_h)]

    print("3. Generating Comparison Verification Report...")
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    
    # PLOT 1: Real UMass Data (Unknown Base/Heat split)
    ax = axes[0]
    sns.scatterplot(data=real_merged, x='temp_C', y='load_kw', ax=ax, alpha=0.7, color='black', label="Total Smart Meter Load")
    
    # Trendline for UMass
    m_real, b_real = np.polyfit(real_merged['temp_C'], real_merged['load_kw'], 1)
    ax.plot(real_merged['temp_C'], m_real * real_merged['temp_C'] + b_real, color='red', linestyle='--', 
            label=f"Heating Coefficient: {m_real:.2f} kW/°C")
    
    ax.invert_xaxis()  # Colder on the right
    ax.set_title("Real UMass AMI (100 Apts)", fontsize=12, fontweight='bold')
    ax.set_xlabel("Outdoor Temperature (°C)")
    ax.set_ylabel("Aggregate Power (kW)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    ax.set_ylim(0, 300)

    # PLOT 2: Gridalyn Equivalent Model (Explicit Base/Heat split)
    ax = axes[1]
    # We plot the base load as one color, and heat + base as another to show stacking
    sns.scatterplot(data=synth_merged, x='temp_C', y='base_kw', ax=ax, alpha=0.4, color='blue', label="Synthetic Non-Heat Baseline")
    sns.scatterplot(data=synth_merged, x='temp_C', y='total_kw', ax=ax, alpha=0.7, color='darkorange', label="Synthetic Total Load (Base + Heat)")
    
    # Trendline for Synthetic
    m_syn, b_syn = np.polyfit(synth_merged['temp_C'], synth_merged['total_kw'], 1)
    ax.plot(synth_merged['temp_C'], m_syn * synth_merged['temp_C'] + b_syn, color='red', linestyle='--', 
            label=f"Heating Coefficient: {m_syn:.2f} kW/°C")

    ax.invert_xaxis()  # Colder on the right
    ax.set_title("Gridalyn RC Model (100 Bldgs)", fontsize=12, fontweight='bold')
    ax.set_xlabel("Outdoor Temperature (°C)")
    ax.set_ylabel("Aggregate Power (kW)")
    ax.grid(True, alpha=0.3)
    ax.legend()
    ax.set_ylim(0, 300)

    plt.suptitle("Stochastic Heating Physics Verification: Real AMI vs Gridalyn Synthetic Engine", fontsize=15, fontweight='bold')
    plt.tight_layout()
    plt.savefig(OUTPUT_IMG, dpi=200, bbox_inches='tight')
    
    print("\n[VERIFICATION RESULTS]")
    print(f"UMass Aggregate Heating Slope:   {m_real:.2f} kW/°C")
    print(f"Gridalyn Aggregate Heating Slope: {m_syn:.2f} kW/°C")
    print(f"\nSaved image to: {OUTPUT_IMG}")

if __name__ == "__main__":
    main()
