"""
generate_substation_cls_data.py

Extracts the entire distribution grid topology (representing a 15 MVA Primary Substation)
and generates high-fidelity stochastic Building baseline and EV flexibility traces.
These are exported to Parquet for the governed CLS project workflow.
"""

import sys
import json
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from tqdm import tqdm
from scipy.ndimage import gaussian_filter1d

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.assets.datagen.data.weather import select_peak_load_day
from gridalyn.assets.datagen.agents import make_buildings, make_ev_chargers, simulate_buildings
from projects.flexibility_cls.scripts.pipeline._summary import summarize_array
from projects.flexibility_cls.scripts.weather_input import load_project_tmy

# Stage-00 Monte-Carlo arrays are the rawest, most cross-environment
# jitter-prone outputs, so they are pinned STATS-PRIMARY (Open Q2 resolution):
# the content hash rides a deliberately COARSE rounding floor (tripwire only),
# strictly coarser than the downstream Stage-01/02 floor.
STAGE00_ROUND_DECIMALS = 3
from projects.flexibility_cls.scripts.config import (
    EV_CHARGER_KW,
    N_REALIZATIONS,
    PROJECT_CACHE_DIR,
    RES_MINUTES,
    SEED,
)

def main():
    print("="*70)
    print("  CLS Substation Data Extractor (5-Min Unified Precision)")
    print("="*70)
    
    # 0. Check for existing cached profiles
    out_dir = ROOT / "projects/flexibility_cls/outputs/data"
    b_path = out_dir / "substation_baseline_mc.parquet"
    ev_path = out_dir / "substation_ev_capability_mc.parquet"
    
    if b_path.exists() and ev_path.exists():
        print(f"[!] Cached stochastic profiles found at {out_dir}.")
        print("    Regenerating files to apply new dynamic variance improvements.")
        # return

    # 1. Load Topology to find N_BUILDINGS
    cache_pg = PROJECT_CACHE_DIR / "pg_graph_cache.pkl"
    if not cache_pg.exists():
        print(
            "[!] Project topology cache not found! Please run "
            "`uv run python projects/flexibility_cls/scripts/pipeline/prepare_topology_cache.py` first."
        )
        sys.exit(1)
        
    print("[1/4] Loading localized Substation topology...")
    with open(cache_pg, "rb") as f:
        pg_graph = pickle.load(f)
        
    n_buildings = len(pg_graph.building_data)
    print(f"  -> Extracted exactly {n_buildings} targeted discrete physical buildings.")
    
    # 2. Setup Substation Weather Environment
    print("[2/4] Loading the pinned project TMY weather input...")
    tmy = load_project_tmy()
    # Use the same 40-hour peak-demand weather window as the congestion forecast
    # and market dispatch stages so building loads and transformer limits are aligned.
    peak_day = select_peak_load_day(tmy, duration_hours=28)
    t_out_1min = peak_day["temp_air"]
    
    # Unified 5-minute resolution for all physics (buildings + EVs)
    t_out = t_out_1min.resample(f"{RES_MINUTES}min").mean()
    n_steps = len(t_out)
    
    # We want 30 Monte Carlo Bounds to define the chance-constrained Substation Envelope
    # Setup DataFrames to hold the 30 macroscopic Substation loads
    ts_index = t_out.index
    df_baseline = pd.DataFrame(index=ts_index)
    df_ev_total = pd.DataFrame(index=ts_index)
    
    print(f"[3/4] Running {N_REALIZATIONS}x Monte Carlo Physics ({RES_MINUTES}-min Unified Resolution)...")
    
    # Progress bar over realizations
    for r in tqdm(range(N_REALIZATIONS)):
        macro_rng = np.random.default_rng(SEED + r)
        
        # Create a smoothed random walk for the temperature offset (weather forecast error varying over time)
        temp_noise = macro_rng.normal(0, 0.5, n_steps)
        smooth_temp_noise = gaussian_filter1d(temp_noise, sigma=24) # 2-hour smoothing window at 5m resolution
        t_offset_trace = float(macro_rng.normal(0, 0.5)) + smooth_temp_noise
        
        # Create a smoothed random walk for the behavioral multiplier (load varying over time)
        # Reduced white noise and static offset to prevent profiles from drifting too far from mean
        white_noise = macro_rng.normal(0, 0.08, n_steps)
        smooth_behav_noise = gaussian_filter1d(white_noise, sigma=12) # 1-hour smoothing window
        behav_mult_trace = float(macro_rng.normal(1.0, 0.01)) + smooth_behav_noise
        
        # A. Buildings at 5-min resolution
        perturbed_temp = t_out + t_offset_trace
        buildings = make_buildings(n_buildings, seed=SEED + r)
        b_results = simulate_buildings(buildings, perturbed_temp, random_seed=SEED + r)
        
        # B. EVs at 5-min resolution (same timestep as buildings)
        # Shift EV average arrival time and vary the spread of arrivals for this specific day
        arrival_shift = float(macro_rng.normal(0, 0.3))
        arrival_std = float(macro_rng.uniform(0.85, 1.25))  # Narrower uniform bounds to avoid flattening the peak too much
        
        evs = make_ev_chargers(
            n=n_buildings, 
            n_evs_per_block=1, 
            charger_kw=EV_CHARGER_KW,
            c_soft_fraction=0.40, 
            seed=SEED + r,
            macro_arrival_shift_h=arrival_shift,
            macro_arrival_std_h=arrival_std
        )
        
        agg_b_load = np.zeros(n_steps)
        agg_ev_load = np.zeros(n_steps)
        
        # Aggregate building loads
        for i in range(n_buildings):
            agg_b_load += b_results[i]["p_total_kw"].values * behav_mult_trace
            
        # Pre-compute EV stochastic 30% penetration mask
        ev_mask = np.random.default_rng(SEED + r).random(n_buildings) < 0.30
        
        # Aggregate EVs at 5-min steps
        for step, ts in enumerate(ts_index):
            current_minute_from_midnight = ts.hour * 60 + ts.minute
            for ev_idx, ev in enumerate(evs):
                if ev_mask[ev_idx]:
                    res = ev.step(minute=current_minute_from_midnight, cls_active=False, dt=RES_MINUTES)
                    agg_ev_load[step] += res["p_ev_kw"]
        
        df_baseline[f"realization_{r}"] = agg_b_load / 1000.0   # Convert to MW
        df_ev_total[f"realization_{r}"] = agg_ev_load / 1000.0  # Convert to MW
        
    print("\n[4/4] Extracting Substation Portfolios to Disk...")
    out_dir = ROOT / "projects/flexibility_cls/outputs/data"
    out_dir.mkdir(parents=True, exist_ok=True)
    
    b_path = out_dir / "substation_baseline_mc.parquet"
    ev_path = out_dir / "substation_ev_capability_mc.parquet"
    
    df_baseline.to_parquet(b_path)
    df_ev_total.to_parquet(ev_path)
    
    print(f"  -> Extracted: {b_path}")
    print(f"  -> Extracted: {ev_path}")
    

    out_outputs = ROOT / "projects/flexibility_cls/outputs/json"
    out_outputs.mkdir(parents=True, exist_ok=True)
    
    summary_data = {
        "n_buildings": n_buildings,
        "resolution_minutes": RES_MINUTES,
        "n_realizations": N_REALIZATIONS,
        "baseline_mean_peak_mw": float(df_baseline.max(axis=0).mean()),
        "ev_mean_peak_mw": float(df_ev_total.max(axis=0).mean()),
        # Stage-00 boundary arrays: stats-primary, coarse tripwire hash.
        "substation_baseline_mc": summarize_array(
            df_baseline.to_numpy(), round_decimals=STAGE00_ROUND_DECIMALS
        ),
        "substation_ev_capability_mc": summarize_array(
            df_ev_total.to_numpy(), round_decimals=STAGE00_ROUND_DECIMALS
        ),
    }
    out_summary = out_outputs / "stochastic_profiles_summary.json"
    out_summary.write_text(
        json.dumps(summary_data, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
        
    print("="*70)
    print("  SUCCESS! Substation data isolated and ready for Jupyter Notebooks.")
    print("="*70)

if __name__ == "__main__":
    main()
