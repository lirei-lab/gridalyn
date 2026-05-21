import sys
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from gridalyn.assets.datagen.agents import make_buildings, simulate_buildings
from gridalyn.assets.datagen.data.weather import download_tmy, select_cold_day

OUTPUT_DIR = ROOT / "examples" / "generated" / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def analyze_building_loads():
    print("Fetching TMY data and simulating buildings...")
    tmy = download_tmy()
    cold_day = select_cold_day(tmy)
    
    # Simulate 50 buildings for sufficient statistical data
    n_buildings = 50
    buildings = make_buildings(n_buildings, seed=42)
    bld_results = simulate_buildings(buildings, cold_day["temp_air"], burnin_hours=6)
    
    print("Simulation complete. Analyzing results...")
    
    all_bg_kw = []
    all_heat_kw = []
    daily_bg_peaks = []
    daily_heat_peaks = []
    daily_bg_energy_kwh = []
    daily_heat_energy_kwh = []
    
    # Extract timeseries
    time_index = cold_day.index
    hours = time_index.hour + time_index.minute / 60.0
    
    plt.figure(figsize=(15, 10))
    
    # Plot 1: Individual Background Load Profiles (Sample of 5)
    plt.subplot(2, 2, 1)
    for i in range(5):
        bg_prof = bld_results[i]["p_bg_kw"].values
        plt.plot(hours, bg_prof, alpha=0.7, label=f'Building {i}')
    plt.title('Individual Base Loads (Non-Heating) - Sample of 5')
    plt.xlabel('Hour of Day')
    plt.ylabel('Power (kW)')
    plt.legend()
    plt.grid(True, linestyle='--', alpha=0.6)
    
    # Process statistics for all buildings
    for i in range(n_buildings):
        bg = bld_results[i]["p_bg_kw"].values
        heat = bld_results[i]["p_heat_kw"].values
        
        all_bg_kw.append(bg)
        all_heat_kw.append(heat)
        
        daily_bg_peaks.append(np.max(bg))
        daily_heat_peaks.append(np.max(heat))
        
        # Energy = sum(kW) * (1 min / 60 min/h) = kWh
        daily_bg_energy_kwh.append(np.sum(bg) / 60.0)
        daily_heat_energy_kwh.append(np.sum(heat) / 60.0)
        
    all_bg_kw = np.array(all_bg_kw)
    all_heat_kw = np.array(all_heat_kw)
    
    # Plot 2: Aggregate Background Load
    plt.subplot(2, 2, 2)
    mean_bg = np.mean(all_bg_kw, axis=0)
    p5_bg = np.percentile(all_bg_kw, 5, axis=0)
    p95_bg = np.percentile(all_bg_kw, 95, axis=0)
    
    plt.plot(hours, mean_bg, color='blue', linewidth=2, label='Mean Base Load')
    plt.fill_between(hours, p5_bg, p95_bg, color='blue', alpha=0.2, label='10th-90th Percentile')
    plt.title('Aggregate Base Load Distribution')
    plt.xlabel('Hour of Day')
    plt.ylabel('Power (kW)')
    plt.legend()
    plt.grid(True, linestyle='--', alpha=0.6)
    
    # Plot 3: Energy Distribution (kWh/day)
    plt.subplot(2, 2, 3)
    data = pd.DataFrame({
        'Base Load (Appliances+DHW)': daily_bg_energy_kwh,
        'Heating Load': daily_heat_energy_kwh
    })
    sns.boxplot(data=data, orient='h')
    plt.title('Daily Energy Consumption per Building (Cold Day)')
    plt.xlabel('Energy (kWh/day)')
    
    # Plot 4: Peak Distribution (kW)
    plt.subplot(2, 2, 4)
    data_peaks = pd.DataFrame({
        'Base Load Peak': daily_bg_peaks,
        'Heating Load Peak': daily_heat_peaks
    })
    sns.boxplot(data=data_peaks, orient='h')
    plt.title('Daily Peak Demand per Building (kW)')
    plt.xlabel('Power (kW)')
    
    plt.tight_layout()
    plot_path = OUTPUT_DIR / 'datagen_calibration_analysis.png'
    plt.savefig(plot_path)
    print(f"Plot saved to {plot_path}")
    
    # Compute summary stats
    print("-" * 40)
    print("CALIBRATION STATISTICS SUMMARY (n=50)")
    print("-" * 40)
    print(f"Base Load Energy (kWh/day): Mean = {np.mean(daily_bg_energy_kwh):.1f}, Std = {np.std(daily_bg_energy_kwh):.1f}")
    print(f"Heating Energy (kWh/day):   Mean = {np.mean(daily_heat_energy_kwh):.1f}, Std = {np.std(daily_heat_energy_kwh):.1f}")
    print(f"Total Daily Energy (kWh):   Mean = {np.mean(np.array(daily_bg_energy_kwh) + np.array(daily_heat_energy_kwh)):.1f}")
    print("-" * 40)
    print(f"Base Load Peak (kW):        Mean = {np.mean(daily_bg_peaks):.1f}, Max = {np.max(daily_bg_peaks):.1f}")
    print(f"Heating Peak (kW):          Mean = {np.mean(daily_heat_peaks):.1f}, Max = {np.max(daily_heat_peaks):.1f}")
    
if __name__ == "__main__":
    analyze_building_loads()
