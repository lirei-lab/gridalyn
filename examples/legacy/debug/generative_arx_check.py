import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

os.makedirs("examples/generated/outputs", exist_ok=True)
from gridalyn.simulators.agents.unmanaged_loads import ParametricArxGenerator
from gridalyn.datagen.data.weather import download_tmy, select_cold_day

def validate_generator():
    print("3. Validating 3,000 Stochastic Homes Generation...")
    gen = ParametricArxGenerator()
    
    # 1. Train the ML models to generate the .pkl files perfectly
    df_m = pd.read_hdf('datasets/hq/meteo.h5')
    df_c = pd.read_hdf('datasets/hq/consumption.h5') / 1000.0
    df_h = pd.read_hdf('datasets/hq/heating.h5') / 1000.0
    df_bg = df_c - df_h
    gen.fit(df_m, df_h, df_bg)
    
    # 2. Re-Load them dynamically
    gen.load()
    
    tmy = download_tmy()
    cold_day = select_cold_day(tmy)
    time_idx = pd.date_range("2024-01-01 00:00:00", periods=len(cold_day["temp_air"]), freq="min")
    temperature_1min = pd.Series(cold_day["temp_air"].values, index=time_idx)
    
    # Resample to 15-minute 
    temperature_15m = temperature_1min.resample('15min').mean()
    
    n_houses = 3000
    # Vectorized Inference generates 3,000 complex trajectories locally
    heat_kw, bg_kw = gen.generate(temperature_15m, n_houses=n_houses)
    outputs_kw = heat_kw + bg_kw
    
    # The output is (96, 3000) for 15-minute data in 1 day
    aggregated_kw = np.sum(outputs_kw, axis=1) / n_houses
    
    print("4. Loading Baseline HQ Ground Truth for the Plotting...")
    df_m = pd.read_hdf('datasets/hq/meteo.h5')
    df_c = pd.read_hdf('datasets/hq/consumption.h5') / 1000.0
    daily_min_temp = df_m['DryBulb'].resample('D').min()
    cold_days = daily_min_temp.sort_values().head(5).index
    
    hq_profiles = []
    avg_home_15m = df_c.sum(axis=1) / 1000.0
    for d in cold_days:
        try:
            day_str = d.strftime('%Y-%m-%d')
            # Extract 96 steps of 15m
            p = avg_home_15m.loc[day_str].values[:96]
            if len(p) == 96:
                hq_profiles.append(p)
        except Exception:
            pass
    hq_avg_profile = np.mean(hq_profiles, axis=0)
    
    print("5. Plotting Result Artifact...")
    fig, ax = plt.subplots(figsize=(10, 6))
    time_axis = np.linspace(0, 24, aggregated_kw.shape[0])
    
    # Plot empirical HQ solid line
    ax.plot(time_axis, hq_avg_profile[:aggregated_kw.shape[0]], label="Empirical Average (Original 1,000 HQ Homes)", color='black', linewidth=3)
    
    # Plot Parametric generated 3,000 homes
    ax.plot(time_axis, aggregated_kw, label=f"Parametric ARX Generation ({n_houses} Novel Homes)", color='magenta', linestyle='--', linewidth=3)
    
    ax.set_title(f"Parametric ARX Generator Validation", fontsize=14, fontweight='bold')
    ax.set_xlabel("Hour of Day", fontsize=12)
    ax.set_ylabel("Power Demand (kW / home)", fontsize=12)
    ax.set_xticks(np.arange(0, 25, 2))
    ax.grid(True, linestyle='--', alpha=0.5)
    ax.legend(loc='upper left', fontsize=11)
    
    plt.tight_layout()
    out_dir = "/home/lirei-lenovo/.gemini/antigravity/brain/f0b96534-c013-4c81-8cdb-4caa2e2e3fbd"
    out_file = os.path.join(out_dir, "arx_generative_validation.png")
    plt.savefig(out_file, dpi=200, bbox_inches='tight')
    print(f"[{out_file}] successfully written!")

if __name__ == "__main__":
    validate_generator()

