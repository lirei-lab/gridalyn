import os
import glob
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

ELECTRIC_DIR = "datasets/umass_data/apartment/2016"
WEATHER_FILE = "datasets/umass_data/apartment-weather/apartment2016.csv"
OUTPUT_IMG = "datasets/umass_data/umass_verification_plots.png"

def main():
    print("1. Loading UMass Weather Data (2016)...")
    weather = pd.read_csv(WEATHER_FILE)
    # the 'time' column is a unix timestamp in US/Eastern
    weather['datetime'] = pd.to_datetime(weather['time'], unit='s', utc=True).dt.tz_convert('EST').dt.tz_localize(None)
    weather.set_index('datetime', inplace=True)
    weather = weather[['temperature']].resample('H').mean()

    print("2. Loading UMass Electric Data for 100 apartments (2016)...")
    # Load first 100 apartments
    csv_files = glob.glob(os.path.join(ELECTRIC_DIR, "Apt*_2016.csv"))[:100]
    
    # We will grab a 7-day winter window (Jan 15 to Jan 21) to save on memory
    start_date = '2016-01-15'
    end_date = '2016-01-21'

    apt_data = {}
    for i, file in enumerate(csv_files):
        df = pd.read_csv(file, header=None, names=['datetime', 'kw'])
        df['datetime'] = pd.to_datetime(df['datetime'])
        df.set_index('datetime', inplace=True)
        # Filter window
        df = df.loc[start_date:end_date]
        apt_data[f'Apt_{i}'] = df['kw']
        if i % 10 == 0:
            print(f"   Loaded {i} / 100 apartments...")

    # Combine into a single minute-resolution dataframe
    print("   Concatenating...")
    df_all_min = pd.DataFrame(apt_data).fillna(0)

    print("3. Analyzing Aggregation & Behavior...")
    
    # Create the plots
    fig = plt.figure(figsize=(16, 12))
    
    # PLOT 1: Individual Behavior (1 Day)
    ax1 = plt.subplot(2, 2, 1)
    day_df = df_all_min.loc['2016-01-15']
    ax1.plot(day_df.index, day_df['Apt_0'], color='blue', alpha=0.7)
    ax1.set_title("Single Apartment Behavior (1 Minute Res)", fontsize=12, fontweight='bold')
    ax1.set_ylabel("Power (kW)")
    ax1.grid(True, alpha=0.3)
    ax1.tick_params(axis='x', rotation=45)

    # PLOT 2: Aggregate Behavior (100 Apts)
    ax2 = plt.subplot(2, 2, 2)
    agg_100 = day_df.sum(axis=1)
    ax2.plot(day_df.index, agg_100, color='red')
    ax2.set_title("Aggregate Behavior (100 Apartments, 1 Minute Res)", fontsize=12, fontweight='bold')
    ax2.set_ylabel("Total Power (kW)")
    ax2.grid(True, alpha=0.3)
    ax2.tick_params(axis='x', rotation=45)

    # PLOT 3: Variance in Aggregation Levels
    ax3 = plt.subplot(2, 2, 3)
    # Calculate Coefficient of Variation (CV) = std / mean for different aggregation sizes
    agg_sizes = [1, 5, 10, 20, 50, 100]
    cvs = []
    hourly_df = df_all_min.resample('H').mean()
    for size in agg_sizes:
        # randomly pick 'size' apartments
        sub = hourly_df.iloc[:, :size].sum(axis=1)
        cvs.append(sub.std() / sub.mean())
    
    ax3.plot(agg_sizes, cvs, marker='o', linestyle='-', color='purple', linewidth=2)
    ax3.set_title("Variance Decay by Aggregation Level", fontsize=12, fontweight='bold')
    ax3.set_xlabel("Number of Apartments Aggregated")
    ax3.set_ylabel("Coefficient of Variation (Std / Mean)")
    ax3.grid(True, alpha=0.3)

    # PLOT 4: Weather Dependency (Temperature vs Load)
    ax4 = plt.subplot(2, 2, 4)
    # Match hourly load with hourly temperature
    agg_hourly = hourly_df.sum(axis=1)
    merged = pd.concat([agg_hourly.rename('load_kw'), weather['temperature']], axis=1).dropna()
    
    sns.scatterplot(data=merged, x='temperature', y='load_kw', ax=ax4, alpha=0.5, color='orange')
    # Trendline
    m, b = np.polyfit(merged['temperature'], merged['load_kw'], 1)
    ax4.plot(merged['temperature'], m*merged['temperature'] + b, color='black', linestyle='--')
    ax4.set_title("Weather Dependency: Aggregate Load vs Temp (°F)", fontsize=12, fontweight='bold')
    ax4.set_xlabel("Temperature (°F)")
    ax4.set_ylabel("Aggregate Load (100 Apts) - kW")
    ax4.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(OUTPUT_IMG, dpi=200, bbox_inches='tight')
    print(f"\n[SUCCESS] Generated visual verification report at: {OUTPUT_IMG}")

if __name__ == "__main__":
    main()
