# %%

import os
from typing import Any, Dict

from pandapower.diagnostic import diagnostic

from gridalyn.adapters.geojson import BuildingDownloader
from gridalyn.core.graph import PowerGridGraph
from gridalyn.viz.interactive import GridPlotter
from gridalyn.simulators.powerflow.builder import PandapowerGridBuilder


def main() -> None:
    """
    This script demonstrates the creation of a power grid graph,
    its visualization, and the building of a pandapower model.
    """
    # Step 0: Configure input file
    polygon_coordinates = [
        [-72.62417036110914, 46.34726673598499],
        [-72.61452837213456, 46.35379678880483],
        [-72.61013276391213, 46.354794761027705],
        [-72.58624610343783, 46.339943052357285],
        [-72.58659312513969, 46.33910452912204],
        [-72.59730468715948, 46.32824092363754],
        [-72.6237240054993, 46.34619741748094],
        [-72.62417036110914, 46.34726673598499],
    ]

    downloader = BuildingDownloader()
    output_dir = "examples/generated/outputs"
    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, "osm_buildings.geojson")
    downloader.download_buildings(
        tuple(tuple(float(c) for c in coord) for coord in polygon_coordinates),  # type: ignore[misc, arg-type]
        output_file,
    )

    # Step 1: Extract building centroids
    pg_graph: PowerGridGraph = PowerGridGraph()
    pg_graph.extract_building_centers_and_areas(output_file)
    # Step 2: Create the LV transformer graph
    max_load_per_building: int = 20
    mv_lv_transformer_capacity: int = 250
    pg_graph.create_lv_graph(max_load_per_building, mv_lv_transformer_capacity)
    pg_graph.extend_graph_with_cim("graph_lv_buses")
    pg_graph.create_building_graph()

    # Step 3: Create the MV substation graph
    hv_mv_transformer_capacity: int = 25000
    pg_graph.create_mv_graph(mv_lv_transformer_capacity, hv_mv_transformer_capacity)
    pg_graph.extend_graph_with_cim("graph_mv_buses")

    # Step 4: Create the HV substation graph
    hv_substation_capacity: int = (
        len(pg_graph.labels_mv) if pg_graph.labels_mv is not None else 0
    ) * hv_mv_transformer_capacity
    pg_graph.create_hv_substation_graph(
        hv_mv_transformer_capacity, hv_substation_capacity
    )
    pg_graph.extend_graph_with_cim("graph_hv_buses")

    # Step 5: Visualize the Power Grid
    plotter: GridPlotter = GridPlotter(pg_graph)
    map_view = plotter.plot_building_and_centroid_graph(
        plot_lv_edges=True, plot_mv_edges=True, plot_hv_edges=True
    )
    # Create output directory if it doesn't exist
    output_dir = "examples/generated/outputs"
    os.makedirs(output_dir, exist_ok=True)

    map_view.save(os.path.join(output_dir, "power_grid_map.html"))
    print(
        f"Grid visualization saved to {os.path.join(output_dir, 'power_grid_map.html')}."
    )

    pg_graph.merge_graphs()
    pg_graph.export_to_graphml(os.path.join(output_dir, "power_grid.graphml"))
    print(f"Export graphml to {os.path.join(output_dir, 'power_grid.graphml')}.")

    # Step 6: Build the pandapower model

    # Example configuration dictionary
    config: Dict[str, Any] = {
        "buses": {
            "lv": {"voltage_kv": 0.48, "type": "b"},
            "mv": {"voltage_kv": 20.0, "type": "b"},
            "hv": {"voltage_kv": 115.0, "type": "b"},
        },
        "lines": {
            "lv": {"std_type": "94-AL1/15-ST1A 0.4", "min_length_km": 0.001},
            "mv": {"std_type": "149-AL1/24-ST1A 10.0", "min_length_km": 0.001},
            "hv": {"std_type": "149-AL1/24-ST1A 10.0", "min_length_km": 0.001},
        },
        "transformers": {
            "lv_mv": {"std_type": "0.63 MVA 20/0.4 kV"},
            "mv_hv": {"std_type": "25 MVA 110/20 kV"},
        },
    }

    # Create an instance of PandapowerGridBuilder
    pp_builder: PandapowerGridBuilder = PandapowerGridBuilder(
        power_grid=pg_graph, config=config
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
        max_r_ohm=diagnostic_params["max_r_ohm"],
        max_x_ohm=diagnostic_params["max_x_ohm"],
        nom_voltage_tolerance=diagnostic_params["nom_voltage_tolerance"],
        numba_tolerance=diagnostic_params["numba_tolerance"],
    )


if __name__ == "__main__":
    main()
# %%
