import os
import pickle
import numpy as np
import pandas as pd
import duckdb

from gridalyn.datagen.data.weather import download_tmy, select_cold_day
from gridalyn.simulators.agents.fleet import make_buildings, simulate_buildings

def main():
    print("====== Extractor Analítico de Poder (DuckDB CQRS) ======")
    
    # 1. Cargar metadatos topológicos cacheados (FalkorDB Proxy)
    output_dir = "examples/generated/outputs"
    cache_pg = os.path.join(output_dir, "pg_graph_cache.pkl")
    cache_pp = os.path.join(output_dir, "pp_net_cache.pkl")
    
    if not os.path.exists(cache_pg) or not os.path.exists(cache_pp):
        print("ERROR: Caches no encontrados. Entrena la red primero.")
        return
        
    with open(cache_pg, "rb") as f:
        pg_graph = pickle.load(f)
    print("Grafo topológico cargado en memoria.")
    
    with open(cache_pp, "rb") as f:
        net = pickle.load(f)
        
    labels_lv = pg_graph.labels_lv
    areas = pg_graph.building_data["Area (sq. meters)"].values
    n_houses = len(areas)
    
    # 2. Reconstruir Simulación Datagen Estocástica (Nivel Hogar Individual)
    print("Obteniendo TMY (Datos del clima local)...")
    tmy = download_tmy()
    cold_day = select_cold_day(tmy)
    temperature = cold_day["temp_air"].values
    
    # IMPORTANTE: Simulamos cada una de las miles de casas independientemente
    # para generar verdadera diversidad estocástica (anti-correlación local).
    print(f"Simulando de forma intensiva {n_houses} Edificios Físicos independientes...")

    buildings = make_buildings(n_houses, seed=42)
    bld_results = simulate_buildings(buildings, cold_day["temp_air"])
    profiles = [bld_results[i]["p_total_kw"].values for i in range(n_houses)]
    
    # 3. Escalamiento (Averaging over time steps to prevent aliasing)
    slice_step = 5  # Resolución en minutos (288 steps x 24h)
    profiles_sliced = [
        np.mean(prof[:len(prof) - (len(prof) % slice_step)].reshape(-1, slice_step), axis=1) 
        for prof in profiles
    ]
    temperature_sliced = temperature[:len(temperature) - (len(temperature) % slice_step)].reshape(-1, slice_step).mean(axis=1)
    time_steps = len(profiles_sliced[0])
    
    # Generar timestamps compatibles con el slider y Kepler
    time_idx = pd.date_range("2024-01-01 00:00:00", periods=time_steps, freq=f"{slice_step}min")
    
    mean_area = areas.mean() if len(areas) > 0 else 1.0
    
    print("Inyectando matrices de Potencia P (MW) sobre los Nodos Espaciales...")
    p_mw_df = pd.DataFrame(index=time_idx, columns=net.load.index)
    
    for idx in net.load.index:
        building_idx = idx % len(areas)
        building_area = areas[building_idx] 
        area_scale = building_area / mean_area 
        
        prof = profiles_sliced[building_idx]
        
        # Datagen ahora arroja kW directos por casa. Escalamos por área y convertimos a MW.
        peak_mw = prof * area_scale / 1000.0
        p_mw_df[idx] = peak_mw
        
    # 4. Formatear para Edge Analytics (DuckDB-Wasm / Parquet)
    p_df = p_mw_df.reset_index().rename(columns={"index": "timestamp"})
    p_long = p_df.melt(id_vars="timestamp", var_name="bus_idx", value_name="p_mw")
    p_long["timestamp"] = p_long["timestamp"].astype(str)
    
    # Expandir temperatura a todos los registros vinculándola a través del timestamp
    # Esto es ineficiente espacialmente pero ultra rápido de consultar (OLAP)
    temp_df = pd.DataFrame({
        "timestamp": time_idx.astype(str),
        "temperature_c": temperature_sliced
    })
    
    print("Calculando uniones en DuckDB...")
    con = duckdb.connect()
    con.register('p_long', p_long)
    con.register('temp_df', temp_df)
    
    parquet_out = "dashboard/public/kepler_timeseries_power.parquet"
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
    
    print(f"ÉXITO: Trajetorias Sensoriales Analíticas exportadas a {parquet_out}!")

if __name__ == "__main__":
    main()
