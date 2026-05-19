import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from gridalyn.simulators.agents.unmanaged_loads import ParametricArxGenerator

def main():
    print("Loading Parametric ARX Generator...")
    gen = ParametricArxGenerator()
    gen.load()

    print("Generating synthetic weather data (24 hours at 15-min freq)...")
    idx = pd.date_range("2022-01-01", periods=96, freq="15min")
    hours = idx.hour + idx.minute / 60.0
    # Simulate a cold winter day: -15C at midnight, dropping to -25C at 6AM, rising to -10C at 3PM
    temp_curve = -15 - 10 * np.sin(2 * np.pi * (hours - 6) / 24)
    temp_series = pd.Series(temp_curve, index=idx)

    n_houses = 1000
    print(f"Generating trajectories for {n_houses} houses...")
    heat_kw, bg_kw = gen.generate(temp_out_series=temp_series, n_houses=n_houses)
    total_kw = heat_kw + bg_kw

    # Compute statistics across the 1000 houses
    mean_total = np.mean(total_kw, axis=1)
    p5_total = np.percentile(total_kw, 5, axis=1)
    p25_total = np.percentile(total_kw, 25, axis=1)
    p75_total = np.percentile(total_kw, 75, axis=1)
    p95_total = np.percentile(total_kw, 95, axis=1)

    mean_bg = np.mean(bg_kw, axis=1)
    p5_bg = np.percentile(bg_kw, 5, axis=1)
    p95_bg = np.percentile(bg_kw, 95, axis=1)

    mean_heat = np.mean(heat_kw, axis=1)
    p5_heat = np.percentile(heat_kw, 5, axis=1)
    p95_heat = np.percentile(heat_kw, 95, axis=1)

    fig, axes = plt.subplots(3, 1, figsize=(10, 12), sharex=True)

    # Plot Total Demand
    ax = axes[0]
    ax.plot(hours, mean_total, color='black', lw=2, label='Mean Total Demand')
    ax.fill_between(hours, p5_total, p95_total, color='blue', alpha=0.2, label='5th-95th Percentile')
    ax.fill_between(hours, p25_total, p75_total, color='blue', alpha=0.4, label='25th-75th Percentile')
    ax.set_title(f'Total Aggregate Demand Expected Profile ({n_houses} Houses)')
    ax.set_ylabel('Power (kW)')
    ax.grid(True, alpha=0.3)
    ax.legend(loc='upper right')

    # Plot Heating Demand
    ax = axes[1]
    ax.plot(hours, mean_heat, color='red', lw=2, label='Mean Heating Demand')
    ax.fill_between(hours, p5_heat, p95_heat, color='red', alpha=0.2, label='5th-95th Percentile')
    ax.set_title('Heating Demand Expected Profile')
    ax.set_ylabel('Power (kW)')
    ax.grid(True, alpha=0.3)
    ax.legend(loc='upper right')

    # Plot Background Demand
    ax = axes[2]
    ax.plot(hours, mean_bg, color='green', lw=2, label='Mean Background Demand')
    ax.fill_between(hours, p5_bg, p95_bg, color='green', alpha=0.2, label='5th-95th Percentile')
    ax.set_title('Background Demand Expected Profile')
    ax.set_ylabel('Power (kW)')
    ax.set_xlabel('Hour of Day')
    ax.grid(True, alpha=0.3)
    ax.legend(loc='upper right')

    plt.tight_layout()
    out_path = "examples/generated/outputs/house_confidence_intervals.png"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    plt.savefig(out_path, dpi=300)
    print(f"Plot saved to {out_path}")

if __name__ == "__main__":
    main()
