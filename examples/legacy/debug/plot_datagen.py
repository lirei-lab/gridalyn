import os
import matplotlib.pyplot as plt
import numpy as np
import sys

# Agregar el root del proyecto para que pueda importar 'gridalyn' fácilmente
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from gridalyn.simulators.agents.fleet import make_buildings, simulate_buildings
from gridalyn.datagen.data.weather import download_tmy, select_cold_day

def main():
    print("Verificando Perfiles Estocásticos de Datagen (Nivel Hogar)...")
    tmy = download_tmy()
    cold_day = select_cold_day(tmy)
    temperature = cold_day["temp_air"].values
    
    # 1. Simular 5 casas independientes pura y duramente
    buildings = make_buildings(n=5, seed=42)
    bld_results = simulate_buildings(buildings, cold_day["temp_air"])
    
    profiles = [bld_results[i]["p_total_kw"].values for i in range(5)]
    
    # 2. Plotting (Matplotlib)
    fig, ax1 = plt.subplots(figsize=(12, 6))
    
    # Downsample by 5 min para ver cómo se verá en la simulación temporal
    slice_step = 5
    time_hr = np.arange(len(profiles[0][::slice_step])) * (slice_step / 60.0)
    
    colors = ['tab:red', 'tab:green', 'tab:orange', 'tab:purple', 'tab:cyan']
    
    for i, prof in enumerate(profiles):
        ax1.plot(time_hr, prof[::slice_step], label=f"Hogar {i+1}", alpha=0.9, 
                 linewidth=1.5, drawstyle="steps-post", color=colors[i])
        
    ax1.set_xlabel("Hora del Día (h)")
    ax1.set_ylabel("Demanda de Potencia (kW)")
    ax1.set_title("Verificación: 5 Casas Físicas Independientes (Día Frío: Extremo Invierno QC)")
    
    ax2 = ax1.twinx()
    ax2.plot(time_hr, temperature[::slice_step], color="tab:blue", linestyle="--", label="Temperatura Exterior (°C)")
    ax2.set_ylabel("Temperatura (°C)", color="tab:blue")
    
    # Combinar leyendas de ejes mixtos
    lines_1, labels_1 = ax1.get_legend_handles_labels()
    lines_2, labels_2 = ax2.get_legend_handles_labels()
    fig.legend(lines_1 + lines_2, labels_1 + labels_2, loc="upper left", bbox_to_anchor=(0.1, 0.9))
    
    plt.grid(True, alpha=0.3)
    
    # 3. Guardar en carpeta local de debug y también en artifacts para que la IA la muestre
    output_local = os.path.join(os.path.dirname(__file__), "datagen_verification.png")
    output_artifact = "/home/lirei-lenovo/.gemini/antigravity/brain/f0b96534-c013-4c81-8cdb-4caa2e2e3fbd/artifacts/datagen_verification.png"
    
    plt.savefig(output_local, dpi=150, bbox_inches='tight')
    
    try:
        os.makedirs(os.path.dirname(output_artifact), exist_ok=True)
        plt.savefig(output_artifact, dpi=150, bbox_inches='tight')
    except Exception as e:
        print(f"Nota: No se guardó en artifacts de Gemini ({e})")
        
    print(f"Gráfico generado exitosamente en: {output_local}")

if __name__ == "__main__":
    main()
