"""
evaluate_transformer_diversity.py

This script takes the topological output from Gridalyn and injects
a full 24-hour meteorological simulation into the physical building footprint geometries.
Instead of running a single snapshot power flow limit, it aggregates the pure time-series 
Demand (kW) to the topological LV transformer level (cluster) to compute Coincident Peaks,
Non-Coincident Peaks, Diversity Factors, and Utilization Margins.

Outputs standard GeoJSONs strictly for Kepler.gl ingestion, allowing visual auditing 
of transformer efficiency versus oversizing across geographical districts.
"""

import sys
import os
import copy
from pathlib import Path
import json

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

# Ensure project root is on PATH
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from gridalyn.foundation.data import datasets
from gridalyn.twin.core.graph import PowerGridGraph
from gridalyn.assets.datagen.data.weather import download_tmy, select_cold_day
from gridalyn.simulation.simulators.agents.fleet import make_buildings, simulate_buildings

# Configuration
N_BLOCK_ARCHETYPES = 5  # Number of random thermal building archetypes to mix 
OUTPUT_DIR = os.path.join(ROOT, "examples", "generated", "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def main():
    print("=" * 60)
    print("  Temporal Transformer Diversity Analysis")
    print("=" * 60)

    # 1. GENERATE PHYSICAL TOPOLOGY
    print("\n[1/4] Generating Spatial Power Grid Topology...")
    input_file = str(datasets.get_dataset_path("buildings_inside_polygon.geojson"))
    pg_graph = PowerGridGraph()
    
    # Process LV layer
    pg_graph.extract_building_centers_and_areas(input_file)
    pg_graph.create_lv_graph(3.84, 250.0)
    pg_graph.extend_graph_with_cim("graph_lv_buses")
    pg_graph.create_building_graph(3.84)
    
    # Extract buildings (leaf nodes) directly from graph_buildings
    building_g = pg_graph.graph_buildings
    
    building_nodes = [
        (n, d) for n, d in building_g.nodes(data=True) 
        if d.get("type", "").startswith("building")
    ]
    print(f"  Extracted {len(building_nodes)} physical buildings.")
    
    # Extract transformer capacities mapped by LV bus
    # The default transformer rating in the examples config is 250 kVA. 
    lv_buses = pg_graph.graph_lv_buses
    transformers = {
        n: 250.0  # Default LV-MV transformer capacity in Gridalyn
        for n, d in lv_buses.nodes(data=True)
        if d.get("type", "").startswith("lv_feeder")
    }
    print(f"  Extracted {len(transformers)} LV Transformers.")

    # Get area mapping to define base-load scale ratios
    areas = [d.get("area", 0.0) for n, d in building_nodes]
    areas_valid = [a for a in areas if a > 0]
    mean_area = np.mean(areas_valid) if areas_valid else 1.0

    # 2. GENERATE LONGITUDINAL TEMPORAL DATAGEN TIMESERIES
    print("\n[2/4] Simulating 24-hr Datagen Baseline Chronological Profiles...")
    print("  Fetching Datagen weather data (TMY)...")
    tmy = download_tmy()
    cold_day = select_cold_day(tmy)
    temperature_curve = cold_day["temp_air"]

    print(f"  Simulating {N_BLOCK_ARCHETYPES} thermal archetypes over 1440 minutes...")
    archetype_blocks = make_buildings(N_BLOCK_ARCHETYPES, seed=42)
    bld_results = simulate_buildings(archetype_blocks, temperature_curve)
    
    # Extract chronological power arrays. Each Datagen "block" = 50 nominal residential houses.
    # We divide by 50 to extract the single-house base archetype array.
    archetype_arrays_kw = [
        bld_results[i]["p_total_kw"].values / 50.0 
        for i in range(N_BLOCK_ARCHETYPES)
    ]

    # 3. TOPOLOGICAL TRACE AGGREGATION & DIVERSITY FACTOR CALCULATION
    print("\n[3/4] Aggregating 1440-minute Traces via Geographical Clusters...")
    
    # Initialize dictionary to hold combined transformer profiles
    cluster_traces = {t_id: [] for t_id in transformers.keys()}
    
    for idx, (b_name, b_data) in enumerate(building_nodes):
        # 1. Pick a random archetype (deterministic but scattered)
        archetype_idx = idx % N_BLOCK_ARCHETYPES
        base_trace = archetype_arrays_kw[archetype_idx]
        
        # 2. Scale exactly to the graphpower assigned physical peak
        p_kw = b_data.get("p_mw", 0.0) * 1000.0
        peak_base = np.max(base_trace)
        scale_ratio = (p_kw / peak_base) if peak_base > 0 else 0.0
        scaled_trace_kw = base_trace * scale_ratio
        
        # 3. Route to parent transformer (integer -> 'lv_feeder_X')
        parent_cluster = b_data.get("cluster")
        target_t_id = parent_cluster if parent_cluster in cluster_traces else f"lv_feeder_{parent_cluster}"
        
        if target_t_id in cluster_traces:
            cluster_traces[target_t_id].append(scaled_trace_kw)

    print("  Calculating Sum-of-Peaks vs Coincident Peaks by Transformer...")
    
    diversity_stats = []
    
    for t_id, traces in cluster_traces.items():
        if not traces:
            continue
            
        t_capacity_kva = transformers[t_id]
            
        # Sum of non-coincident peaks (kW)
        sum_non_coincident_peaks_kw = sum(np.max(t) for t in traces)
        
        # Coincident Trace (kW)
        coincident_trace_kw = np.sum(traces, axis=0) # sum min-by-min arrays!
        coincident_peak_kw = np.max(coincident_trace_kw) # get highest synchronous point
        
        diversity_factor = sum_non_coincident_peaks_kw / coincident_peak_kw if coincident_peak_kw > 0 else 1.0
        
        # Utilization Margin (Percentage)
        # Assuming pf ~ 1.0 here, Utilization = Coincident Peak / Transformer Installed kVA
        utilization_pct = (coincident_peak_kw / t_capacity_kva) * 100 if t_capacity_kva > 0 else 0.0

        # Geographical mapping (LV Bus center)
        t_data = lv_buses.nodes[t_id]
        
        if "x" not in t_data or "y" not in t_data:
            continue
            
        diversity_stats.append({
            "transformer_id": str(t_id),
            "geometry": Point(t_data["y"], t_data["x"]), # GeoJSON strictly (Longitude, Latitude)
            "installed_kva": float(t_capacity_kva),
            "non_coincident_peak_kw": float(sum_non_coincident_peaks_kw),
            "coincident_peak_kw": float(coincident_peak_kw),
            "diversity_factor": float(diversity_factor),
            "utilization_margin_pct": float(utilization_pct),
            "connected_customers": int(len(traces))
        })

    # 4. EXPORT METRICS TO GEOJSON FOR KEPLER.GL
    print(f"\n[4/4] Writing Diversity Analytics Geometry to Disk. (Found {len(diversity_stats)} valid clusters)")
    
    if len(diversity_stats) == 0:
        print("ERROR: No valid transformer stats calculated! Check cluster mapping.")
        return
    
    gdf_transformers = gpd.GeoDataFrame(diversity_stats, crs="EPSG:4326")
    geojson_out = os.path.join(OUTPUT_DIR, "transformer_diversity_stats.geojson")
    gdf_transformers.to_file(geojson_out, driver="GeoJSON")
    
    # Print high-level statistical verification to the terminal
    avg_df = gdf_transformers["diversity_factor"].mean()
    max_df = gdf_transformers["diversity_factor"].max()
    avg_util = gdf_transformers["utilization_margin_pct"].mean()
    mean_conn = gdf_transformers["connected_customers"].mean()
    
    oversized = len(gdf_transformers[gdf_transformers["utilization_margin_pct"] < 50])
    
    print("=====================================================")
    print("  TRANSFORMER SIMULATION REPORT (24 HOURS)")
    print("=====================================================")
    print(f"  Total Valid Transformers:    {len(gdf_transformers)}")
    print(f"  Average Connected Homes:     {mean_conn:.1f}")
    print(f"  Average Diversity Factor:    {avg_df:.2f} (Max: {max_df:.2f})")
    print(f"  Average Utilization Margin:  {avg_util:.1f} %")
    print(f"  Severely Oversized Trafos:   {oversized} units (< 50% Peak Coincident Loading)")
    print(f"")
    print(f"  -> Generated Kepler Map: {geojson_out}")
    print("=====================================================")


if __name__ == "__main__":
    main()
