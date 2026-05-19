# %%
# %%
import os
from typing import Any, Dict

import networkx as nx
from pandapower.diagnostic import diagnostic

from gridalyn.foundation.data import datasets
from gridalyn.twin.core.graph import PowerGridGraph
from gridalyn.interfaces.viz.interactive import GridPlotter
from gridalyn.simulation.simulators.powerflow.builder import PandapowerGridBuilder


def main() -> None:
    """
    This script demonstrates the creation of a power grid graph,
    its visualization, and the building of a pandapower model.
    """
    # Step 0: Configure input file
    input_file: str = str(datasets.get_dataset_path("buildings_inside_polygon.geojson"))

    # Step 1: Extract building centroids
    pg_graph: PowerGridGraph = PowerGridGraph()
    pg_graph.extract_building_centers_and_areas(input_file)

    output_dir = "examples/generated/outputs"
    os.makedirs(output_dir, exist_ok=True)

    # Export building data to JSON
    building_data_output_filepath = os.path.join(output_dir, "buildings_data.json")
    pg_graph.export_building_data_to_json(building_data_output_filepath)
    print(f"Building data exported to {building_data_output_filepath}")

    # Load the main configuration
    import json
    with open("configs/grid/config.json", "r") as f:
        config = json.load(f)
        
    # Step 2: Create the LV transformer graph
    max_load_per_building = config["loads"]["max_load_per_building"]
    diversity_factor_lv = config["loads"].get("diversity_factor_lv", 5.0)
    diversity_factor_mv = config["loads"].get("diversity_factor_mv", 1.3)
    diversity_factor_hv = config["loads"].get("diversity_factor_hv", 1.1)
    
    mv_lv_transformer_capacity = config["transformers"]["lv_mv"]["capacity_kva"]
    capacity_utilization_factor = config["transformers"]["lv_mv"]["utilization_margin"]
    
    pg_graph.create_lv_graph(
        max_load_per_building, 
        mv_lv_transformer_capacity, 
        capacity_utilization_factor, 
        diversity_factor_lv
    )
    pg_graph.extend_graph_with_cim("graph_lv_buses")
    pg_graph.create_building_graph(max_load_per_building)
    
    # Export building graph to GraphML
    building_output_filepath = os.path.join(output_dir, "buildings_graph.graphml")
    # Clean NoneType values as GraphML does not support them
    clean_buildings = pg_graph.graph_buildings.copy()
    for n, d in clean_buildings.nodes(data=True):
        for k, v in list(d.items()):
            if v is None: d[k] = ""
    for u, v, d in clean_buildings.edges(data=True):
        for k, val in list(d.items()):
            if val is None: d[k] = ""
            
    nx.write_graphml(clean_buildings, building_output_filepath)
    print(f"Building graph exported to {building_output_filepath}")

    # Step 3: Create the MV substation graph
    hv_mv_transformer_capacity = config["transformers"]["mv_hv"]["capacity_kva"]
    pg_graph.create_mv_graph(mv_lv_transformer_capacity, hv_mv_transformer_capacity, diversity_factor_mv)
    pg_graph.extend_graph_with_cim("graph_mv_buses")

    # Step 4: Create the HV substation graph
    hv_substation_capacity = (
        len(pg_graph.labels_mv) if pg_graph.labels_mv is not None else 0
    ) * hv_mv_transformer_capacity
    pg_graph.create_hv_substation_graph(
        hv_mv_transformer_capacity, hv_substation_capacity, diversity_factor_hv
    )
    pg_graph.extend_graph_with_cim("graph_hv_buses")

    # Step 5: Visualize the Power Grid
    plotter: GridPlotter = GridPlotter(pg_graph)
    map_view = plotter.plot_building_and_centroid_graph(
        plot_lv_edges=True, plot_mv_edges=True, plot_hv_edges=True
    )
    map_view.save(os.path.join(output_dir, "power_grid_map.html"))
    print("Grid visualization saved to power_grid_map.html.")

    # Step 6: Build the pandapower model

    # Build pandapower configuration from the loaded config.json
    # (avoids hardcoded voltage/transformer mismatches)
    mv_hv_std = config["transformers"]["mv_hv"]["std_type"]
    is_custom = config["transformers"]["mv_hv"].get("custom_type", False)

    pp_config: Dict[str, Any] = {
        "buses": config["buses"],
        "lines": config["lines"],
        "transformers": {
            "lv_mv": dict(config["transformers"]["lv_mv"]),
            "mv_hv": {
                **dict(config["transformers"]["mv_hv"]),
                "std_type": mv_hv_std,
                "custom_type": is_custom,
            },
        },
    }

    # Create an instance of PandapowerGridBuilder
    pp_builder: PandapowerGridBuilder = PandapowerGridBuilder(
        power_grid=pg_graph, config=pp_config
    )

    # Build the grid components
    pp_builder.build_lv_buses_and_lines()  # Create LV buses and lines
    pp_builder.build_mv_buses_and_lines()  # Create MV buses and lines
    pp_builder.build_hv_buses_and_lines()  # Create HV buses and lines

    pp_builder.build_loads_from_graph_buildings()

    # Validate bus-to-node mapping
    pp_builder.validate_network_consistency()

    pp_builder.build_lv_mv_power_transformers()  # Create LV-MV transformers
    pp_builder.build_mv_hv_power_transformers()  # Create MV-HV transformers
    pp_builder.connect_hv_bus_to_ext_grid()  # Connect HV buses to external grid

    # Step 7: Export or display the pandapower network
    pp_net = pp_builder.get_pandapower_net()

    # Merge graphs and export to GraphML
    pg_graph.merge_graphs()
    output_filepath = os.path.join(output_dir, "power_grid.graphml")
    pg_graph.export_to_graphml(output_filepath)
    print(f"Power grid graph exported to {output_filepath}")

    diagnostic_params = {
        "report_style": "detailed",
        "warnings_only": False,
        "return_result_dict": True,
        "overload_scaling_factor": 0.001,
        "lines_min_length_km": 0.0005,
        "min_r_ohm": 0.0001,
        "min_x_ohm": 0.0001,
        "max_r_ohm": 100,
        "max_x_ohm": 100,
        "nom_voltage_tolerance": 0.3,
        "numba_tolerance": 1e-5,
    }

    diagnostic(
        pp_net,
        report_style=diagnostic_params["report_style"],
        warnings_only=diagnostic_params["warnings_only"],
        return_result_dict=diagnostic_params["return_result_dict"],
        overload_scaling_factor=diagnostic_params["overload_scaling_factor"],
        lines_min_length_km=diagnostic_params["lines_min_length_km"],
        min_r_ohm=diagnostic_params["min_r_ohm"],
        min_x_ohm=diagnostic_params["min_x_ohm"],
        max_x_ohm=diagnostic_params["max_x_ohm"],
        nom_voltage_tolerance=diagnostic_params["nom_voltage_tolerance"],
        numba_tolerance=diagnostic_params["numba_tolerance"],
    )

    # Step 8: Cache the base topologies for downstream evaluating scripts
    import pickle
    cache_pg = os.path.join(output_dir, "pg_graph_cache.pkl")
    cache_pp = os.path.join(output_dir, "pp_net_cache.pkl")
    
    with open(cache_pg, "wb") as f:
        pickle.dump(pg_graph, f)
    with open(cache_pp, "wb") as f:
        pickle.dump(pp_net, f)
    print("Cached spatial grid and pandapower model to disk for downstream evaluation.")

    # Step 9: Print Grid Topology Summary
    print("\n" + "="*50)
    print("GRID TOPOLOGY SUMMARY:")
    print("="*50)
    v_lv = config["buses"]["lv"]["voltage_kv"]
    v_mv = config["buses"]["mv"]["voltage_kv"]
    v_hv = config["buses"]["hv"]["voltage_kv"]
    print(f"Total Buildings Managed:      {len(pp_net.load)}")
    print(f"Total LV Buses (Pillars):     {len(pp_net.bus[pp_net.bus.vn_kv == v_lv])}")
    print(f"Total MV Buses (Feeders):     {len(pp_net.bus[pp_net.bus.vn_kv == v_mv])}")
    print(f"Total HV Buses (Substation):  {len(pp_net.bus[pp_net.bus.vn_kv == v_hv])}")
    
    lv_mv_trafo = len(pp_net.trafo[pp_net.trafo.vn_lv_kv == v_lv])
    mv_hv_trafo = len(pp_net.trafo[pp_net.trafo.vn_lv_kv == v_mv])
    s_mva = config["transformers"]["mv_hv"]["capacity_kva"] / 1000
    print(f"\nLV-MV Transformers (250 kVA): {lv_mv_trafo}")
    print(f"MV-HV Transformers ({s_mva:.0f} MVA):  {mv_hv_trafo}")
    
    print(f"\nTotal Line Segments:          {len(pp_net.line)}")
    total_len = pp_net.line.length_km.sum()
    print(f"Total Cable Distance:         {total_len:.2f} km")
    print("="*50 + "\n")

if __name__ == "__main__":
    main()
# %%
