import os
import pickle
import matplotlib.pyplot as plt
import numpy as np
import sys

# Agregar el root del proyecto para importar módulos correctamente
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from gridalyn.simulators.agents.fleet import make_buildings, simulate_buildings
from gridalyn.datagen.data.weather import download_tmy, select_cold_day

def main():
    print("Iniciando Cálculo: Agregación de 3,235 Edificios Físicos...")
    
    # Extraer el conteo real de casas de los metadatos de Gridalyn
    output_dir = os.path.join(os.path.dirname(__file__), "..", "outputs")
    cache_pg = os.path.join(output_dir, "pg_graph_cache.pkl")
    
    with open(cache_pg, "rb") as f:
        pg_graph = pickle.load(f)
        
    areas = pg_graph.building_data["Area (sq. meters)"].values
    n_houses = len(areas)
    
    print(f"Obteniendo Clima Severo TMY (-22°C)...")
    tmy = download_tmy()
    cold_day = select_cold_day(tmy)
    temperature = cold_day["temp_air"].values
    
    print(f"Simulando las trayectorias de los {n_houses} hogares simultáneamente...")
    buildings = make_buildings(n=n_houses, seed=42)
    bld_results = simulate_buildings(buildings, cold_day["temp_air"])
    
    # Matriz [3235, 1440] de perfiles en kW
    profiles_matrix = np.array([bld_results[i]["p_total_kw"].values for i in range(n_houses)])
    
    # 2. Agregación Global
    # Escalar cada casa a proporción de su área, como lo hace el Core Físico
    mean_area = areas.mean() if len(areas) > 0 else 1.0
    area_scales = areas / mean_area
    
    # P_total en MW: ((kW_por_casa * Escala_Área) / 1000). Sumado por el eje Y (para todos los t)
    # Esto da el Megavataje (MW) Neto Agregado del sistema entero
    scaled_profiles = profiles_matrix * area_scales[:, np.newaxis] 
    aggregated_profile_mw = scaled_profiles.sum(axis=0) / 1000.0
    
    # 3. Plotting
    print("Graficando el Perfil Sistémico Agregado (Macroscópico)...")
    fig, ax1 = plt.subplots(figsize=(12, 6))
    
    slice_step = 5
    time_hr = np.arange(len(aggregated_profile_mw[::slice_step])) * (slice_step / 60.0)
    
    # Trazamos el Mega-Consumo
    ax1.plot(time_hr, aggregated_profile_mw[::slice_step], color="#c0392b", linewidth=3, label="Demanda Agregada Fuerte (MW)")
    
    ax1.set_xlabel("Hora del Día (h)", fontweight='bold')
    ax1.set_ylabel("Demanda Sistémica Neta (MW)", color="#c0392b", fontweight='bold')
    ax1.set_title(f"Agregación Total del Parque: {n_houses} Hogares Físicos (Diversity Smoothing)", fontsize=14)
    
    # Temperatura Externa
    ax2 = ax1.twinx()
    ax2.plot(time_hr, temperature[::slice_step], color="#2980b9", linestyle="--", linewidth=2.5, label="Temperatura Exterior (°C)")
    ax2.set_ylabel("Temperatura (°C)", color="#2980b9", fontweight='bold')
    
    # Rellenar bajo la curva de potencia
    ax1.fill_between(time_hr, aggregated_profile_mw[::slice_step], alpha=0.15, color='#e74c3c')
    
    lines_1, labels_1 = ax1.get_legend_handles_labels()
    lines_2, labels_2 = ax2.get_legend_handles_labels()
    fig.legend(lines_1 + lines_2, labels_1 + labels_2, loc="upper right", bbox_to_anchor=(0.85, 0.85))
    
    plt.grid(True, alpha=0.3, linestyle='--')
    
    output_local = os.path.join(os.path.dirname(__file__), "datagen_aggregate.png")
    output_artifact = "/home/lirei-lenovo/.gemini/antigravity/brain/f0b96534-c013-4c81-8cdb-4caa2e2e3fbd/artifacts/datagen_aggregate.png"
    
    plt.savefig(output_local, dpi=150, bbox_inches='tight')
    try:
        os.makedirs(os.path.dirname(output_artifact), exist_ok=True)
        plt.savefig(output_artifact, dpi=150, bbox_inches='tight')
    except Exception as e:
        print(f"Error guardando artefacto: {e}")
        
    print(f"Éxito: El gráfico agregado se encuentra en {output_local}")

if __name__ == "__main__":
    main()
