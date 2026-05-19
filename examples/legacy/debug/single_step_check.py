import os
import pickle
import sys
import pandas as pd
import numpy as np
import pandapower as pp
import pandapower.timeseries as ts
from pandapower.timeseries.data_sources.frame_data import DFData
from pandapower.control import ConstControl

# Agregar el root del proyecto
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from gridalyn.simulators.agents.fleet import make_buildings, simulate_buildings
from gridalyn.datagen.data.weather import download_tmy, select_cold_day

def main():
    print("====== SCRIPT DE DIAGNÓSTICO DE ÚNICO HILO (1 REALIZACIÓN, 3 PASOS DE TIEMPO) ======")
    
    # 1. Cargar topología
    cache_path = os.path.join(os.path.dirname(__file__), "..", "outputs", "pp_net_cache.pkl")
    with open(cache_path, "rb") as f:
        net = pickle.load(f)
    print(f"✅ Red cargada: {len(net.bus)} buses, {len(net.trafo)} trafos, {len(net.load)} loads.")

    # 2. Clima y Simulacion Física de las 3235 cargas 
    print("⏳ Generando física térmica para las 3,235 casas...")
    tmy = download_tmy()
    cold_day = select_cold_day(tmy)
    buildings = make_buildings(n=len(net.load), seed=42)
    bld_results = simulate_buildings(buildings, cold_day["temp_air"])
    
    # 3. Empaquetado para Pandapower Timeseries (recrear matriz de inyección)
    profiles_matrix = np.array([bld_results[b.unit_id]["p_total_kw"].values for b in buildings])
    
    with open(os.path.join(os.path.dirname(__file__), "..", "outputs", "pg_graph_cache.pkl"), "rb") as f:
        pg_graph = pickle.load(f)
    areas = pg_graph.building_data["Area (sq. meters)"].values
    mean_area = areas.mean() if len(areas) > 0 else 1.0
    area_scales = areas / mean_area
    
    scaled_profiles = profiles_matrix * area_scales[:, np.newaxis]
    p_mw_df = pd.DataFrame(scaled_profiles.T / 1000.0)
    p_mw_df.columns = net.load.index.astype(str)
    
    # 4. Inyección al TimeSeries Control
    steps_to_run = 288  # Simulamos el día frío completo (24h)
    ds = DFData(p_mw_df.iloc[:steps_to_run, :])
    ConstControl(net, element='load', variable='p_mw', element_index=net.load.index, 
                 data_source=ds, profile_name=net.load.index.astype(str))
    
    ow = ts.OutputWriter(net, time_steps=range(steps_to_run), output_path=None)
    ow.log_variable('res_bus', 'vm_pu')
    
    print("\n🚀 Iniciando Pandapower KLU Engine sin paralelismo y con Logs Visibles...")
    
    def run_klu(net_obj, **kwargs):
        kwargs["init"] = "flat"
        pp.runpp(net_obj, lightsim2grid=True, **kwargs)

    # Quitamos np.errstate para que explote libremente y nos diga la línea original!
    print("---------------------------------------------------------")
    ts.run_timeseries(net, time_steps=range(steps_to_run), run=run_klu, verbose=True)
    print("---------------------------------------------------------")
    
    print(f"✅ Simulación pura completada con éxito. vm_pu shape: {ow.output['res_bus.vm_pu'].shape}")

if __name__ == "__main__":
    main()
