"""
Run a compact Monte Carlo power-flow tutorial with weather-dependent load data.

By default the tutorial writes only to `examples/generated/outputs`. The archived
Kepler/dashboard-public export can still be requested explicitly for compatibility
with older demonstrations.
"""

import argparse
import json
import sys

from gridalyn.foundation.data import datasets
from gridalyn.simulation.simulators.powerflow.runner import MonteCarloSimulationManager


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-legacy-dashboard-public",
        action="store_true",
        help="Also write archived dashboard/public Kepler artifacts.",
    )
    args = parser.parse_args(argv)

    print("Initializing Multi-level Stochastic Assessor...")
    
    # Load explicit grid network configuration dynamically from JSON
    config_path = "configs/grid/config.json"
    print(f"Loading configuration from: {config_path}")
    with open(config_path, "r") as f:
        config = json.load(f)
        
    sim_config = config.get("simulation", {})
    n_realizations = sim_config.get("n_realizations", 30)
    resolution_minutes = sim_config.get("resolution_minutes", 5)
    
    # Instantiate the formal Parallel Core module
    manager = MonteCarloSimulationManager(
        input_file=str(datasets.get_dataset_path("buildings_inside_polygon.geojson")),
        cache_dir="examples/generated/outputs",
        config=config,
    )
    
    # Execute full spatial multi-realization scaling in 5 minute increments
    manager.run_monte_carlo(n_realizations=n_realizations, resolution_minutes=resolution_minutes)

    if not args.allow_legacy_dashboard_public:
        print(
            "Monte Carlo tutorial completed. Skipping archived dashboard/public "
            "exports; pass --allow-legacy-dashboard-public to generate them."
        )
        return
    
    # ---------------------------------------------------------
    # EXPORT PIPELINE (Single Responsibility Separation)
    # ---------------------------------------------------------
    import os
    from gridalyn.interfaces.viz.interactive import GridPlotter
    from gridalyn.twin.io.geo import (
        export_pp_to_geojson,
        export_timeseries_to_kepler_parquet,
        export_power_traces_to_kepler_parquet
    )
    
    output_dir = "dashboard/public"
    
    # 1. Stochastic visualizations
    plot_path = os.path.join(output_dir, "stochastic_metrics.png")
    plotter = GridPlotter(manager.pg_graph)
    plotter.plot_stochastic_bounds(manager.mc_ext_p_mw, manager.mc_raw_p_mw, manager.mc_max_line, manager.resolution_minutes, plot_path)
    
    voltage_map = plotter.plot_voltage_deviations_folium(manager.pp_net)
    voltage_map.save(os.path.join(output_dir, "voltage_deviations_map_datagen.html"))
    
    # 2. Kepler.gl Static Topology Export (GeoJSON)
    export_pp_to_geojson(manager.pp_net, output_dir)
    
    # 3. Kepler.gl Temporal Dynamics Export (Parquet)
    if manager.mc_spatial_v:
        scenario_idx = 0
        export_timeseries_to_kepler_parquet(
            manager.pp_net,
            spatial_v_scenario=manager.mc_spatial_v[scenario_idx],
            spatial_line_scenario=manager.mc_spatial_line[scenario_idx],
            output_dir=output_dir,
            resolution_minutes=manager.resolution_minutes
        )
        export_power_traces_to_kepler_parquet(
            manager.pg_graph, 
            manager.pp_net, 
            scenario_idx=scenario_idx, 
            resolution_minutes=manager.resolution_minutes, 
            output_dir=output_dir,
            generator_type=sim_config.get("generator", "parametric")
        )
    
if __name__ == "__main__":
    main(sys.argv[1:])
