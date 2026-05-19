import os
import json
import warnings
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, LineString


def _warn_legacy_kepler_export() -> None:
    warnings.warn(
        "Kepler/dashboard-public exporters are legacy. Current dashboard data "
        "should be published through instances/default/digital_twin/timeseries and "
        "instances/default/digital_twin/dashboard/catalog.json.",
        DeprecationWarning,
        stacklevel=3,
    )


def export_pp_to_geojson(net, output_dir: str):
    """
    Exports a pandapower network's spatial nodes and edges to GeoJSON files
    compatible with Kepler.gl and modern GIS tooling.
    
    Args:
        net: A fully constructed pandapower network.
        output_dir: String output path where the geojson files will be dumped.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    print("\n====== Exporting Results for Kepler.gl ======")
    
    bus_details = net.bus
    res_bus = getattr(net, "res_bus", pd.DataFrame(index=bus_details.index))
    
    # 1. Coordinate Parsing
    if "geo" in bus_details.columns:
        def extract_coords(geo_str):
            try:
                if pd.notna(geo_str):
                    data = json.loads(geo_str.replace("'", '"'))
                    return data.get("coordinates", [0, 0])
            except Exception:
                pass
            return [0, 0]
            
        coords = bus_details["geo"].apply(extract_coords)
        bus_x = coords.apply(lambda c: c[0]) 
        bus_y = coords.apply(lambda c: c[1]) 
    else:
        bus_x = pd.Series(0, index=bus_details.index)
        bus_y = pd.Series(0, index=bus_details.index)
    
    # 2. Nodes Export
    nodes = []
    for bus_idx in bus_details.index:
        x, y = bus_x.at[bus_idx], bus_y.at[bus_idx]
        vm_pu = res_bus.at[bus_idx, 'vm_pu'] if bus_idx in res_bus.index else None
        p_mw = res_bus.at[bus_idx, 'p_mw'] if bus_idx in res_bus.index else None
        bus_name = bus_details.at[bus_idx, 'name'] if bus_idx in bus_details.index else str(bus_idx)
        bus_category = "LV" if isinstance(bus_name, str) and "lv_" in bus_name else "MV"
        
        nodes.append({
            'geometry': Point(y, x),
            'bus_idx': int(bus_idx),
            'name': str(bus_name),
            'category': bus_category,
            'vm_pu': float(vm_pu) if pd.notna(vm_pu) else None,
            'p_mw': float(p_mw) if pd.notna(p_mw) else None
        })
        
    nodes_gdf = gpd.GeoDataFrame(nodes, crs="EPSG:4326")
    nodes_out_path = os.path.join(output_dir, "grid_nodes_results.geojson")
    nodes_gdf.to_file(nodes_out_path, driver="GeoJSON")
    print(f"  Exported {len(nodes_gdf)} Nodes to {nodes_out_path}")
    
    # 3. Edges Export
    lines = []
    res_line = getattr(net, "res_line", pd.DataFrame(index=net.line.index))
    line_details = net.line
    
    for line_idx in line_details.index:
        from_bus = line_details.at[line_idx, 'from_bus']
        to_bus = line_details.at[line_idx, 'to_bus']
        loading = res_line.at[line_idx, 'loading_percent'] if line_idx in res_line.index else None
        
        from_bus_name = bus_details.at[from_bus, 'name'] if from_bus in bus_details.index else ""
        line_category = "LV" if isinstance(from_bus_name, str) and "lv_" in from_bus_name else "MV"
        
        p1 = (bus_y.at[from_bus], bus_x.at[from_bus]) if from_bus in bus_x.index else None
        p2 = (bus_y.at[to_bus], bus_x.at[to_bus]) if to_bus in bus_x.index else None
        
        if p1 and p2:
            lines.append({
                'geometry': LineString([p1, p2]),
                'line_idx': int(line_idx),
                'category': line_category,
                'loading_percent': float(loading) if pd.notna(loading) else None
            })
            
    if lines:
        lines_gdf = gpd.GeoDataFrame(lines, crs="EPSG:4326")
        lines_out_path = os.path.join(output_dir, "grid_lines_results.geojson")
        lines_gdf.to_file(lines_out_path, driver="GeoJSON")
        print(f"  Exported {len(lines_gdf)} Lines to {lines_out_path}")

def export_timeseries_to_kepler_parquet(net, spatial_v_scenario, spatial_line_scenario, output_dir: str, resolution_minutes: int = 5):
    """
    Exports time-series numpy arrays of voltage and line loading to massive tabular Parquet files
    using DuckDB. This enables Kepler.gl to animate the simulation data across time without
    memory overloads.
    
    Args:
        net: The pandapower configuration grid.
        spatial_v_scenario: Numpy Array (time_steps, buses) of voltage p.u.
        spatial_line_scenario: Numpy Array (time_steps, lines) of loading_percent.
        output_dir: String output path where the parquet files will be stored.
        resolution_minutes: The temporal resolution step for the animation indexing.
    """
    _warn_legacy_kepler_export()
    import duckdb
    os.makedirs(output_dir, exist_ok=True)
    
    print("\n====== DuckDB Kepler.gl Parquet Temporal Exporter ======")
    
    # 1. Coordinate Parsing Extraction (same logic as GeoJSON)
    bus_details = net.bus
    if "geo" in bus_details.columns:
        def extract_coords(geo_str):
            try:
                if pd.notna(geo_str):
                    data = json.loads(geo_str.replace("'", '"'))
                    return data.get("coordinates", [0, 0])
            except Exception:
                pass
            return [0, 0]
            
        coords = bus_details.columns.get_indexer(["geo"])
        coords = bus_details["geo"].apply(extract_coords)
        bus_x = coords.apply(lambda c: c[0]).values
        bus_y = coords.apply(lambda c: c[1]).values
    else:
        bus_x = np.zeros(len(bus_details))
        bus_y = np.zeros(len(bus_details))

    # Pre-build node geometry reference frame
    category_list = ["LV" if isinstance(name, str) and "lv_" in name else "MV" for name in bus_details['name']] if 'name' in bus_details.columns else ["MV"] * len(bus_details)
    buses_df = pd.DataFrame({
        "bus_idx": bus_details.index.values,
        "lon": bus_y,
        "lat": bus_x,
        "category": category_list
    })
    
    # Pre-build line geometry reference frame
    line_details = net.line.copy()
    line_cat = []
    for fbus in line_details['from_bus']:
        fname = bus_details.at[fbus, 'name'] if fbus in bus_details.index and 'name' in bus_details.columns else ""
        line_cat.append("LV" if isinstance(fname, str) and "lv_" in fname else "MV")
    line_details['category'] = line_cat
    
    # Vectorized extraction of source and target coordinates relying on the buses_df indexing
    # We join lines on bus_idx to fetch from_buses coordinates
    line_geo_df = line_details[["from_bus", "to_bus", "category"]].reset_index().rename(columns={"index": "line_idx"})
    line_geo_df = line_geo_df.merge(buses_df.drop(columns=["category"]), left_on="from_bus", right_on="bus_idx", suffixes=("", "_from"))
    line_geo_df = line_geo_df.rename(columns={"lon": "lon_from", "lat": "lat_from"}).drop(columns=["bus_idx"])
    
    line_geo_df = line_geo_df.merge(buses_df, left_on="to_bus", right_on="bus_idx", suffixes=("", "_to"))
    line_geo_df = line_geo_df.rename(columns={"lon": "lon_to", "lat": "lat_to"}).drop(columns=["bus_idx"])

    # Number of simulation steps
    n_steps = spatial_v_scenario.shape[0]
    
    # Generate true timestamps for Kepler.gl
    time_idx = pd.date_range("2024-01-01 00:00:00", periods=n_steps, freq=f"{resolution_minutes}min")
    
    # === Flattening Tensors to Tabular Formats (using Pandas melt for safety & speed) ===
    # Nodes Matrix
    v_df = pd.DataFrame(spatial_v_scenario, index=time_idx, columns=bus_details.index.values)
    v_df = v_df.reset_index().rename(columns={"index": "timestamp"})
    v_long = v_df.melt(id_vars="timestamp", var_name="bus_idx", value_name="v_pu")
    v_long["timestamp"] = v_long["timestamp"].astype(str) # DuckDB prefers raw string bounds for Kepler integration
    
    # Lines Matrix
    l_df = pd.DataFrame(spatial_line_scenario, index=time_idx, columns=net.line.index.values)
    l_df = l_df.reset_index().rename(columns={"index": "timestamp"})
    l_long = l_df.melt(id_vars="timestamp", var_name="line_idx", value_name="loading_percent")
    l_long["timestamp"] = l_long["timestamp"].astype(str)
    
    # 3. Fast Join and Dump using DuckDB Memory Instances
    con = duckdb.connect()
    con.register('v_long', v_long)
    con.register('buses_df', buses_df)
    con.register('l_long', l_long)
    con.register('line_geo_df', line_geo_df)
    
    node_parquet = os.path.join(output_dir, "kepler_timeseries_nodes.parquet")
    line_parquet = os.path.join(output_dir, "kepler_timeseries_lines.parquet")
    
    print("  Executing DuckDB Node spatial JOIN & Parquet creation...")
    con.execute(f"""
        COPY (
            SELECT 
                v.timestamp,
                b.bus_idx,
                b.lon,
                b.lat,
                v.v_pu,
                b.category
            FROM v_long v
            JOIN buses_df b ON v.bus_idx = b.bus_idx
            ORDER BY v.timestamp
        ) TO '{node_parquet}' (FORMAT PARQUET, COMPRESSION 'SNAPPY');
    """)
    
    print("  Executing DuckDB Line spatial JOIN & Parquet creation...")
    # For lines, kepler supports GeoJSON strings natively inside the Parquet format or explicit source/target coordinates.
    # We will export the source/target lon lats and tell the user to configure Arc/Line layer in Kepler!
    con.execute(f"""
        COPY (
            SELECT 
                l_ts.timestamp,
                geo.line_idx,
                geo.lon_from,
                geo.lat_from,
                geo.lon_to,
                geo.lat_to,
                l_ts.loading_percent,
                geo.category
            FROM l_long l_ts
            JOIN line_geo_df geo ON l_ts.line_idx = geo.line_idx
            ORDER BY l_ts.timestamp
        ) TO '{line_parquet}' (FORMAT PARQUET, COMPRESSION 'SNAPPY');
    """)
    
    print(f"  Success: Extracted {n_steps} temporal states to parquet!")
    print(f"  -> Nodes: {node_parquet}")
    print(f"  -> Lines: {line_parquet}")


def export_power_traces_to_kepler_parquet(
    pg_graph,
    pp_net,
    scenario_idx: int,
    resolution_minutes: int,
    output_dir: str,
    generator_type: str = "parametric",
):
    """
    Reconstructs the precise independent building thermodynamic trajectories 
    for the given parallel scenario, extracting the load profiles back into DuckDB Parquet
    without having saturated the multiprocessing IPC pipes during the simulation Phase.
    """
    _warn_legacy_kepler_export()
    from gridalyn.simulation.simulators.agents.fleet import make_buildings, simulate_buildings
    from gridalyn.assets.datagen.data.weather import download_tmy, select_cold_day
    import duckdb

    print("\n====== DuckDB Kepler.gl Parquet Temporal Exporter (Power Traces CQRS) ======")

    # 1. Fetch cached topology and TMY 
    labels_lv = pg_graph.labels_lv
    areas = pg_graph.building_data["Area (sq. meters)"].values
    n_houses = len(areas)
    seed = 42 + scenario_idx
    macro_rng = np.random.default_rng(seed)
    
    tmy = download_tmy()
    print(f"Re-simulating explicit generator for Scenario {scenario_idx} (Seed {seed})...")
    
    tmy = download_tmy()
    cold_day = select_cold_day(tmy)

    slice_step = int(resolution_minutes)
    target_freq = f"{slice_step}min"
    
    from gridalyn.assets.datagen.core import GridLoadFacade

    # Mirror run_single_realization() so the node history parquet represents
    # the same stochastic scenario used for voltage and line-loading exports.
    t_offset = float(macro_rng.normal(0, 1.5))
    perturbed_temp_air = cold_day["temp_air"] + t_offset
    heat_kw, bg_kw = GridLoadFacade.generate_loads(
        generator_type=generator_type,
        df_weather=perturbed_temp_air,
        n_houses=n_houses,
        resolution_minutes=resolution_minutes,
        seed=seed
    )
    
    total_kw_matrix = heat_kw + bg_kw

    time_steps_len = total_kw_matrix.shape[0]
    ar1_macro = np.zeros(time_steps_len, dtype=np.float32)
    rho_macro = 0.95
    shock_std = 0.04 * np.sqrt(1 - rho_macro**2)
    ar1_macro[0] = macro_rng.normal(0, 0.04)
    for t_step in range(1, time_steps_len):
        ar1_macro[t_step] = rho_macro * ar1_macro[t_step - 1] + macro_rng.normal(0, shock_std)
    total_kw_matrix = total_kw_matrix * (1.0 + ar1_macro)[:, np.newaxis]
    
    # Natively sliced trace for injection
    profiles_sliced = [total_kw_matrix[:, i] for i in range(n_houses)]
    
    # Downsample the raw temperature trace so it perfectly mirrors the temporal map index
    native_res_temp = cold_day["temp_air"].resample(target_freq).mean().interpolate()
    temperature_sliced = native_res_temp.values
    time_steps = len(profiles_sliced[0])

    time_idx = pd.date_range("2024-01-01 00:00:00", periods=time_steps, freq=f"{slice_step}min")
    print("Injecting P (MW) matrices onto Spatial Nodes...")
    p_mw_df = pd.DataFrame(index=time_idx, columns=pp_net.load.index)

    for idx in pp_net.load.index:
        building_idx = idx % len(profiles_sliced)
        prof = profiles_sliced[building_idx]
        peak_mw = prof  / 1000.0
        p_mw_df[idx] = peak_mw

    p_df = p_mw_df.reset_index().rename(columns={"index": "timestamp"})
    p_long = p_df.melt(id_vars="timestamp", var_name="bus_idx", value_name="p_mw")
    p_long["timestamp"] = p_long["timestamp"].astype(str)

    temp_df = pd.DataFrame({
        "timestamp": time_idx.astype(str),
        "temperature_c": temperature_sliced
    })

    con = duckdb.connect()
    con.register('p_long', p_long)
    con.register('temp_df', temp_df)

    parquet_out = os.path.join(output_dir, "kepler_timeseries_power.parquet")
    con.execute(f"""
        COPY (
            SELECT 
                p.timestamp,
                p.bus_idx,
                p.p_mw,
                t.temperature_c
            FROM p_long p
            JOIN temp_df t ON p.timestamp = t.timestamp
            ORDER BY p.timestamp
        ) TO '{parquet_out}' (FORMAT PARQUET, COMPRESSION 'SNAPPY');
    """)
    print(f"  Success: Extracted 288 analytical temporal states to {parquet_out}")
