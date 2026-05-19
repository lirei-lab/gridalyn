import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

os.makedirs("examples/generated/outputs", exist_ok=True)
from gridalyn.simulators.agents.unmanaged_loads import ParametricArxGenerator
from gridalyn.datagen.data.weather import download_tmy, select_cold_day

def main():
    print("1. Loading Stochastic Parametric ARX Core...")
    gen = ParametricArxGenerator()
    gen.load()
    
    
    print("2. Generating Highly Volatile Homes...")
    tmy = download_tmy()
    cold_day = select_cold_day(tmy)
    time_idx = pd.date_range("2024-01-01 00:00:00", periods=len(cold_day["temp_air"]), freq="min")
    temperature_1min = pd.Series(cold_day["temp_air"].values, index=time_idx)
    
    # Resample to 15-minute 
    temperature_15m = temperature_1min.resample('15min').mean()
    
    # Predict step-by-step
    heat_30, bg_30 = gen.generate(temperature_15m, n_houses=30)
    outputs_kw_30 = heat_30 + bg_30
    
    # Generate the huge macro-aggregation of 3,000 homes to prove convergence
    heat_3000, bg_3000 = gen.generate(temperature_15m, n_houses=3000)
    outputs_kw_3000 = heat_3000 + bg_3000
    
    time_axis = np.linspace(0, 24, 96)
    
    print("3. Plotting Spaghetti Map...")
    fig, ax = plt.subplots(figsize=(12, 6))
    
    # Plot all 30 individual homes faintly
    ax.plot(time_axis, outputs_kw_30, color='purple', alpha=0.3, linewidth=1.5)
    
    # Plot the sample mean of specifically these 30 homes (It will be heavily jagged due to small N)
    avg_30 = np.mean(outputs_kw_30, axis=1)
    ax.plot(time_axis, avg_30, color='orange', linewidth=3, label="Local Sample Mean (30 Homes)")
    
    # Plot the mathematical expected shape of all of them (the true physical center)
    avg_3000 = np.mean(outputs_kw_3000, axis=1)
    ax.plot(time_axis, avg_3000, color='darkred', linewidth=4, label="Universal Smooth Mean (3,000 Homes)")
    
    ax.set_title(f"Stochastic Generative Validation: 30 Synthetic Individual Load Traces", fontsize=14, fontweight='bold')
    ax.set_xlabel("Hour of Day", fontsize=12)
    ax.set_ylabel("Power Demand (kW)", fontsize=12)
    ax.set_xticks(np.arange(0, 25, 2))
    
    # Limit to reasonable display scale for individual house bounds (0 - 15 kW typically)
    ax.set_ylim(-1, 20)
    
    ax.grid(True, linestyle='--', alpha=0.5)
    ax.legend(loc='upper right', fontsize=11)
    
    plt.tight_layout()
    out_dir = "/home/lirei-lenovo/.gemini/antigravity/brain/f0b96534-c013-4c81-8cdb-4caa2e2e3fbd"
    out_file = os.path.join(out_dir, "arx_100_spaghetti.png")
    plt.savefig(out_file, dpi=200, bbox_inches='tight')
    print(f"[{out_file}] successfully written!")

if __name__ == "__main__":
    main()
