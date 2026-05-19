import os
import time
import pickle
import random
import json
import hashlib
import concurrent.futures
import warnings
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
import networkx as nx
import pandapower as pp
from pandapower.diagnostic import diagnostic
from pandapower.timeseries import DFData, run_timeseries, OutputWriter
from pandapower.control import ConstControl
from tqdm import tqdm

from gridalyn.twin.core.graph import PowerGridGraph
from gridalyn.interfaces.viz.interactive import GridPlotter
from gridalyn.simulation.simulators.powerflow.builder import PandapowerGridBuilder
from gridalyn.assets.datagen.data.weather import download_tmy, select_cold_day
from gridalyn.simulation.simulators.agents.fleet import make_buildings, simulate_buildings


def run_single_realization(sim_idx, seed, net_json_path, cold_temp_air, n_blocks, labels_lv, areas, resolution_minutes=5, generator_type="parametric"):
    """
    Standalone physics container for evaluating a single specific random trajectory.
    Isolated entirely so ProcessPoolExecutor can serialize it to a distant CPU core.
    """
    # [CRITICAL TLS FIX]: We must import lightsim2grid absolutely FIRST in the spawned 
    # worker to reserve static TLS block for OpenMP/OpenBLAS. Otherwise, dlopen fails 
    # silently with 'cannot allocate memory in static TLS block', Pandapower silently 
    # falls back to fragile Python Scipy.spsolve, and Numpy mathematically crashes with NaNs!
    import lightsim2grid
    import numpy as np
    
    np.seterr(all='ignore')
    with open(net_json_path, "rb") as f:
        net = pickle.load(f)
    macro_rng = np.random.default_rng(seed)
    # Global Temperature Shift: The entire weather curve shifts uniformly by N(0, 1.5)°C
    t_offset = float(macro_rng.normal(0, 1.5))
    perturbed_temp_air = cold_temp_air + t_offset
    
    # 2. Simulate thermal diversity for this scenario
    # Given the core update, n_blocks now explicitly means n_houses (thousands)
    n_houses = n_blocks
    
    from gridalyn.assets.datagen.core import GridLoadFacade
    heat_kw, bg_kw = GridLoadFacade.generate_loads(
        generator_type=generator_type,
        df_weather=perturbed_temp_air,
        n_houses=n_houses,
        resolution_minutes=resolution_minutes,
        seed=seed
    )
    
    # The output is (time_steps, n_houses)
    total_kw_matrix = heat_kw + bg_kw
    
    # Global Behavioral Wander: Instead of a flat single multiplier (which makes all realizations perfectly parallel),
    # the entire population stochastically wanders over the day via Macroscopic AR(1) noise (rho=0.95 -> extremely smooth).
    time_steps_len = total_kw_matrix.shape[0]  # Respect natively computed simulation resolution
    ar1_macro = np.zeros(time_steps_len, dtype=np.float32)
    rho_macro = 0.95
    shock_std = 0.04 * np.sqrt(1 - rho_macro**2)
    ar1_macro[0] = macro_rng.normal(0, 0.04)
    for t_step in range(1, time_steps_len):
        ar1_macro[t_step] = rho_macro * ar1_macro[t_step-1] + macro_rng.normal(0, shock_std)
    behavioral_wander = 1.0 + ar1_macro
    
    # 3. Apply macro-stochastic Behavioral Wander (to simulate non-parallel temporal social drifting)
    profiles_sliced = [(total_kw_matrix[:, i] * behavioral_wander) for i in range(n_houses)]
    
    time_steps = len(profiles_sliced[0])
    
    p_mw_df = pd.DataFrame(index=range(time_steps), columns=net.load.index)
    q_mvar_df = pd.DataFrame(index=range(time_steps), columns=net.load.index)
    
    for idx in net.load.index:
        building_idx = idx % len(profiles_sliced)
        prof = profiles_sliced[building_idx]
        
        # Datagen naturally peaks around 9.5 kW. 
        peak_mw = prof / 1000.0
        p_mw_df[idx] = peak_mw
        q_mvar_df[idx] = peak_mw * 0.1
        
    num_nans = p_mw_df.isna().sum().sum() + np.isinf(p_mw_df).sum().sum()
    if num_nans > 0:
        print(f"\\n[!] Worker {sim_idx}: Detected {num_nans} NaN/Inf anomalies from building simulator! Truncating to 0.0...")
        p_mw_df = p_mw_df.fillna(0.0).replace([np.inf, -np.inf], 0.0).infer_objects(copy=False)
        q_mvar_df = q_mvar_df.fillna(0.0).replace([np.inf, -np.inf], 0.0).infer_objects(copy=False)

    raw_datagen_p_mw = p_mw_df.sum(axis=1).values
    
    # 4. Inject timeseries controllers
    ds_p = DFData(p_mw_df)
    ds_q = DFData(q_mvar_df)
    ConstControl(net, element='load', variable='p_mw', element_index=net.load.index, data_source=ds_p, profile_name=net.load.index)
    ConstControl(net, element='load', variable='q_mvar', element_index=net.load.index, data_source=ds_q, profile_name=net.load.index)
    
    # 5. Simulate using the extremely fast C++ KLU Solver (lightsim2grid)
    ow = OutputWriter(net, time_steps=range(time_steps))
    ow.log_variable('res_bus', 'vm_pu')
    ow.log_variable('res_line', 'loading_percent')
    ow.log_variable('res_trafo', 'loading_percent')
    ow.log_variable('res_ext_grid', 'p_mw')
    
    def run_klu(net_obj, **kwargs):
        # Bypasses Python/SciPy SuperLU and hooks into C++/Eigen/KLU
        pp.runpp(net_obj, lightsim2grid=True, **kwargs)
        
    import traceback
    try:
        with np.errstate(divide='ignore', invalid='ignore', over='ignore', under='ignore'):
            run_timeseries(net, time_steps=range(time_steps), run=run_klu, verbose=False)
    except Exception as exc:
        print(f"\\n🔥 [TRÁGICO CRASH] Trabajador {sim_idx} falló estrepitosamente! Traceback completo:")
        traceback.print_exc()
        raise exc
    # 6. Extract lightweight numpy arrays
    ext_p_mw = ow.output["res_ext_grid.p_mw"].sum(axis=1).abs().values.copy()
    max_line = ow.output["res_line.loading_percent"].max(axis=1).values.copy()
    mean_line = ow.output["res_line.loading_percent"].mean(axis=1).values.copy()
    spatial_v = ow.output["res_bus.vm_pu"].values.copy()
    spatial_line = ow.output["res_line.loading_percent"].values.copy()
    spatial_trafo = ow.output["res_trafo.loading_percent"].values.copy()
    
    return {
        "sim_idx": sim_idx,
        "ext_p_mw": ext_p_mw,
        "max_line": max_line,
        "mean_line": mean_line,
        "raw_datagen_p_mw": raw_datagen_p_mw,
        "spatial_v": spatial_v,
        "spatial_line": spatial_line,
        "spatial_trafo": spatial_trafo,
        "time_steps": time_steps
    }


from gridalyn.api import Interface
from gridalyn.twin.io.geo import export_pp_to_geojson, export_timeseries_to_kepler_parquet


class MonteCarloSimulationManager(Interface):
    """
    High-level Simulation engine for building massive Grid ontologies
    and orchestrating C++ Parallel Monte Carlo engines.
    """
    
    def __init__(self, input_file: str, cache_dir: str = "examples/generated/outputs", config: Optional[Dict[str, Any]] = None):
        super().__init__(config=config)
        self.input_file = input_file
        self.cache_dir = cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)
        
        # Multidimensional result structures
        self.mc_ext_p_mw = []
        self.mc_max_line = []
        self.mc_mean_line = []
        self.mc_raw_p_mw = []
        self.mc_spatial_v = []
        self.mc_spatial_line = []
        self.mc_spatial_trafo = []
        self.resolution_minutes = 15

    def _prepare_grid(self, force_rebuild: bool = False):
        """Loads heavily pickled base grids, or regenerates from scratch and caches over Operations Interface."""
        cache_pg = os.path.join(self.cache_dir, "pg_graph_cache.pkl")
        cache_pp = os.path.join(self.cache_dir, "pp_net_cache.pkl")
        cache_meta = os.path.join(self.cache_dir, "grid_cache_meta.json")
        cache_schema = "gridalyn-powerflow-cache-v2"
        config_hash = hashlib.sha256(
            json.dumps(self.config, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        
        cache_is_current = False
        if os.path.exists(cache_pg) and os.path.exists(cache_pp) and os.path.exists(cache_meta):
            try:
                with open(cache_meta, "r") as f:
                    meta = json.load(f)
                cache_is_current = (
                    meta.get("config_hash") == config_hash
                    and meta.get("cache_schema") == cache_schema
                )
            except Exception:
                cache_is_current = False

        if not force_rebuild and os.path.exists(cache_pg) and os.path.exists(cache_pp) and cache_is_current:
            print("====== Stage 1: Loading Cached Grid Generation ======")
            try:
                with open(cache_pg, "rb") as f:
                    self.power_grid = pickle.load(f)
                self.pg_graph = self.power_grid # Map abstract pg to local interface logic
                with open(cache_pp, "rb") as f:
                    self.net = pickle.load(f)
                self.pp_net = self.net
                print(f"Loaded Cached Grid: {len(self.pp_net.bus)} buses, {len(self.pp_net.line)} lines.")
                return
            except ModuleNotFoundError as exc:
                print(f"====== Stage 1: Ignoring stale cache from old package layout: {exc} ======")
                force_rebuild = True

        if force_rebuild or not cache_is_current or not os.path.exists(cache_pg) or not os.path.exists(cache_pp):
            if not force_rebuild and os.path.exists(cache_pg) and os.path.exists(cache_pp):
                print("====== Stage 1: Cached Grid Stale or Unversioned; Rebuilding ======")
            else:
                print("====== Stage 1: Spatial Grid Generation ======")
            # Uses the Native Interface
            self.load_grid(self.input_file)
            self.build_pp()
            self.pg_graph = self.power_grid
            self.pp_net = self.net

            if self.pp_net is None:
                print("[!] Pandapower network build failed — pp_net_cache.pkl will NOT be written.")
                print("[!] Check transformer std_type in config.json — must be a valid pandapower type.")
                # Still cache the spatial graph (buildings, topology)
                with open(cache_pg, "wb") as f:
                    pickle.dump(self.pg_graph, f)
                print("Cached spatial grid (topology only) to disk.")
                raise RuntimeError("Pandapower network build failed; aborting simulation.")

            # Export buildings to match original script functionality
            building_data_output_filepath = os.path.join(self.cache_dir, "buildings_data.json")
            self.pg_graph.export_building_data_to_json(building_data_output_filepath)

            with open(cache_pg, "wb") as f:
                pickle.dump(self.pg_graph, f)
            with open(cache_pp, "wb") as f:
                pickle.dump(self.net, f)
            with open(cache_meta, "w") as f:
                json.dump(
                    {
                        "cache_schema": cache_schema,
                        "config_hash": config_hash,
                        "config": self.config,
                    },
                    f,
                    indent=2,
                    sort_keys=True,
                )
            print("Cached spatial grid and pandapower model to disk for future runs.")

        return cache_pp



    def run_monte_carlo(self, n_realizations: int = 30, resolution_minutes: int = 5, force_rebuild: bool = False):
        """
        Orchestrates Parallel Physics Evaluation across all System CPU Cores, effectively 
        collapsing thousands of thermal grid configurations down into memory.
        """
        import time
        from tqdm import tqdm
        
        self.resolution_minutes = resolution_minutes
        
        # Validate/Generate base network geometry
        net_json_path = self._prepare_grid(force_rebuild=force_rebuild)
        
        print("\n====== Stage 2 & 3: Monte Carlo Stochastic Simulation (PARALLEL ACCELERATOR) ======")
        t_start = time.time()
        
        print(f"Utilizing base grid Pickled topology {net_json_path} for parallel extraction.")
        
        print("Fetching Datagen weather data (TMY) for the ensemble...")
        tmy = download_tmy()
        cold_day = select_cold_day(tmy)
        
        labels_lv = self.pg_graph.labels_lv
        areas = self.pg_graph.building_data["Area (sq. meters)"].values
        # Sobreescribimos n_blocks para enviarle a la rutina paralela el total estricto de inmuebles
        n_houses = len(areas)
        import multiprocessing
        import concurrent.futures
        
        # Loky/Joblib reuses workers by default, causing accumulated C++ memory leaks inside Pandas/LightSim2Grid matrices.
        # This inevitably triggers OOM fragmentation and Numpy FloatingPointError random crashes down the line. 
        # By enforcing 'spawn' and 'max_tasks_per_child=1', we violently nuke the worker's address space after EACH realization.
        concurrency = max(1, os.cpu_count() // 2)
        print(f"\nDispatching {n_realizations} realizations across {concurrency} isolated spawn-workers (Nuking RAM per loop)...")
        
        # Decouple the series completely from pandas internal BlockManager locks to prevent ProcessPool spawn crashes
        clean_temp_series = pd.Series(
            cold_day["temp_air"].values.copy(), 
            index=cold_day["temp_air"].index.copy()
        )
        
        
        generator_type = self.config.get("simulation", {}).get("generator", "parametric")
        
        args_list = []
        for sim in range(n_realizations):
            args_list.append((
                sim,
                42+sim,
                net_json_path,
                clean_temp_series,
                n_houses,
                labels_lv,
                areas,
                resolution_minutes,
                generator_type
            ))
            
        results = []
        # Require Python 3.11+ for max_tasks_per_child in ProcessPoolExecutor
        ctx = multiprocessing.get_context("spawn")
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=concurrency, 
            mp_context=ctx,
            max_tasks_per_child=1
        ) as executor:
            # We map the jobs
            futures = {executor.submit(run_single_realization, *args): args[0] for args in args_list}
            
            for future in tqdm(concurrent.futures.as_completed(futures), total=n_realizations, desc="Parallel Stochastic Engines"):
                try:
                    res = future.result()
                    results.append(res)
                except Exception as exc:
                    print(f"\\n[!] Worker realization failed with internal error: {exc}")
                
        # Sort spatially so trace alignment is clean
        results.sort(key=lambda x: x["sim_idx"])
        
        # Accumulate the distributed memory tensors back onto Orchestrator Layer
        for res in results:
            self.mc_ext_p_mw.append(res["ext_p_mw"])
            self.mc_max_line.append(res["max_line"])
            self.mc_mean_line.append(res["mean_line"])
            self.mc_raw_p_mw.append(res["raw_datagen_p_mw"])
            self.mc_spatial_v.append(res["spatial_v"])
            self.mc_spatial_line.append(res["spatial_line"])
            self.mc_spatial_trafo.append(res["spatial_trafo"])
            
        print("\n====== Aggregating Dimensional Stochastic Matrices ======")
        mc_spatial_v_np = np.array(self.mc_spatial_v)
        mc_spatial_line_np = np.array(self.mc_spatial_line)
        mc_spatial_trafo_np = np.array(self.mc_spatial_trafo)
        
        # Cast the deepest analytical structural boundaries into the original un-simulated pandapower object
        # Taking MIN for voltage to find voltage-drops.
        self.pp_net.res_bus = getattr(self.pp_net, "res_bus", pd.DataFrame(index=self.pp_net.bus.index))
        self.pp_net.res_line = getattr(self.pp_net, "res_line", pd.DataFrame(index=self.pp_net.line.index))
        self.pp_net.res_trafo = getattr(self.pp_net, "res_trafo", pd.DataFrame(index=self.pp_net.trafo.index))
        
        self.pp_net.res_bus["vm_pu"] = mc_spatial_v_np.min(axis=(0, 1))  
        self.pp_net.res_line["loading_percent"] = mc_spatial_line_np.max(axis=(0, 1)) 
        self.pp_net.res_trafo["loading_percent"] = mc_spatial_trafo_np.max(axis=(0, 1)) 
        
        t_end = time.time()
        print(f"\n[BENCHMARK] Parallel {n_realizations}x Simulation Execution Time: {t_end - t_start:.2f} seconds")

        self._verify_grid_stats()
        legacy_export_dir = self.config.get("simulation", {}).get("legacy_mc_export_dir")
        if legacy_export_dir:
            self.export_to_parquet(legacy_export_dir)

    def export_to_parquet(self, out_dir: Optional[str] = None) -> None:
        """
        Export Monte Carlo building load timeseries to Parquet.

        This is a legacy snapshot helper. Active project and digital-twin
        workflows should use project output data directories and
        `digital_twin/timeseries`.
        Callers that still need the old two-file snapshot must pass `out_dir`
        explicitly, for example through `simulation.legacy_mc_export_dir`.

        Writes two files:
          substation_baseline_mc.parquet
            Columns: realization_0 ... realization_N  (aggregate building load in kW)

          substation_powerflow_mc.parquet
            Columns: realization_0 ... realization_N  (HV ext-grid active power in MW)
        """
        if out_dir is None:
            warnings.warn(
                "MonteCarloSimulationManager.export_to_parquet() no longer "
                "defaults to paper/data. Pass an explicit out_dir only for "
                "legacy Monte Carlo snapshots.",
                DeprecationWarning,
                stacklevel=2,
            )
            return

        if not self.mc_raw_p_mw:
            print("[!] export_to_parquet: no MC results to export — run run_monte_carlo() first.")
            return

        os.makedirs(out_dir, exist_ok=True)

        # ── 1. Building baseline (kW, aggregate across all loads) ──────────
        n_steps = len(self.mc_raw_p_mw[0])
        bldg_df = pd.DataFrame(
            {f"realization_{r}": self.mc_raw_p_mw[r] * 1000.0  # MW → kW
             for r in range(len(self.mc_raw_p_mw))},
        )
        bldg_path = os.path.join(out_dir, "substation_baseline_mc.parquet")
        bldg_df.to_parquet(bldg_path, index=False)

        # ── 2. Power-flow result at ext-grid bus (MW, from KLU solver) ─────
        pf_df = pd.DataFrame(
            {f"realization_{r}": self.mc_ext_p_mw[r]
             for r in range(len(self.mc_ext_p_mw))},
        )
        pf_path = os.path.join(out_dir, "substation_powerflow_mc.parquet")
        pf_df.to_parquet(pf_path, index=False)

        n_r    = len(self.mc_raw_p_mw)
        pk_kw  = bldg_df.median(axis=1).max()
        print(f"\n====== Parquet Export (Single Source of Truth) ======")
        print(f"  {n_r} realizations × {n_steps} steps")
        print(f"  Building median peak: {pk_kw/1e3:.1f} MW")
        print(f"  → {bldg_path}")
        print(f"  → {pf_path}")
        print("=====================================================\n")


    def _verify_grid_stats(self):
        print("\n====== Verification: Grid Statistics ======")
        vm_pu = self.pp_net.res_bus.vm_pu.dropna()
        if len(vm_pu) > 0:
            min_v, max_v = vm_pu.min(), vm_pu.max()
            under_voltage = (vm_pu < 0.95).sum() / len(vm_pu) * 100
            over_voltage = (vm_pu > 1.05).sum() / len(vm_pu) * 100
            
            print(f"Voltage (p.u.): Min={min_v:.3f}, Max={max_v:.3f}")
            if under_voltage > 0 or over_voltage > 0:
                print(f"  WARNING: {under_voltage:.1f}% buses < 0.95 p.u. | {over_voltage:.1f}% buses > 1.05 p.u.")
            else:
                print("  SUCCESS: All buses within 0.95 - 1.05 p.u. limits.")
            
        line_loading = self.pp_net.res_line.loading_percent.dropna()
        if len(line_loading) > 0:
            mean_line, max_line = line_loading.mean(), line_loading.max()
            overloaded_lines = (line_loading > 100).sum()
            
            print(f"Line Loading (%): Mean={mean_line:.1f}%, Max={max_line:.1f}%")
            if overloaded_lines > 0:
                print(f"  WARNING: {overloaded_lines} lines are overloaded (>100% capacity)!")
            else:
                print("  SUCCESS: No lines are overloaded.")
            
        trafo_loading = self.pp_net.res_trafo.loading_percent.dropna()
        if len(trafo_loading) > 0:
            mean_trafo, max_trafo = trafo_loading.mean(), trafo_loading.max()
            overloaded_trafos = (trafo_loading > 100).sum()
            
            print(f"Trafo Loading (%): Mean={mean_trafo:.1f}%, Max={max_trafo:.1f}%")
            if overloaded_trafos > 0:
                print(f"  WARNING: {overloaded_trafos} transformers are overloaded (>100% capacity)!")
            else:
                print("  SUCCESS: No transformers are overloaded.")
        print("===========================================\n")
