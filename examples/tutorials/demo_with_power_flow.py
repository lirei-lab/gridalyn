import os
from typing import Any, Dict

import networkx as nx
import pandapower as pp
from pandapower.diagnostic import diagnostic

from gridalyn.foundation.data import datasets
from gridalyn.twin.core.graph import PowerGridGraph
from gridalyn.interfaces.viz.interactive import GridPlotter
from gridalyn.simulation.simulators.powerflow.builder import PandapowerGridBuilder


class PowerFlowAnalysis:
    def __init__(self, input_file: str, output_dir: str = "examples/generated/outputs"):
        self.input_file = input_file
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        self.pg_graph = PowerGridGraph()
        self.pp_net = None
        self.plotter = None
        self.config = {
            "loads": {"max_load_per_building": 10},
            "buses": {
                "lv": {"voltage_kv": 0.4, "type": "b"},
                "mv": {"voltage_kv": 20.0, "type": "b"},
                "hv": {"voltage_kv": 110.0, "type": "b"},
            },
            "lines": {
                "lv": {"std_type": "94-AL1/15-ST1A 0.4", "min_length_km": 0.001},
                "mv": {"std_type": "149-AL1/24-ST1A 10.0", "min_length_km": 0.001},
                "hv": {"std_type": "149-AL1/24-ST1A 10.0", "min_length_km": 0.001},
            },
            "transformers": {
                "lv_mv": {"std_type": "0.63 MVA 20/0.4 kV", "capacity_kva": 250},
                "mv_hv": {"std_type": "25 MVA 110/20 kV", "capacity_kva": 25000},
            },
        }

    def run(self):
        self.extract_building_data()
        self.create_grid_graphs()
        self.visualize_grid()
        self.build_pandapower_model()
        self.run_power_flow()
        self.visualize_results()

    def extract_building_data(self):
        self.pg_graph.extract_building_centers_and_areas(self.input_file)
        building_data_output_filepath = os.path.join(
            self.output_dir, "buildings_data.json"
        )
        self.pg_graph.export_building_data_to_json(building_data_output_filepath)
        print(f"Building data exported to {building_data_output_filepath}")

    def create_grid_graphs(self):
        max_load_per_building = self.config["loads"]["max_load_per_building"]
        mv_lv_transformer_capacity = self.config["transformers"]["lv_mv"]["capacity_kva"]
        self.pg_graph.create_lv_graph(max_load_per_building, mv_lv_transformer_capacity)
        self.pg_graph.extend_graph_with_cim("graph_lv_buses")
        self.pg_graph.create_building_graph()
        building_output_filepath = os.path.join(
            self.output_dir, "buildings_graph.graphml"
        )
        
        # Sanitize None values before GraphML export
        for _, d in self.pg_graph.graph_buildings.nodes(data=True):
            for k, v in d.items():
                if v is None:
                    d[k] = ""
        for _, _, d in self.pg_graph.graph_buildings.edges(data=True):
            for k, v in d.items():
                if v is None:
                    d[k] = ""
                    
        nx.write_graphml(self.pg_graph.graph_buildings, building_output_filepath)
        print(f"Building graph exported to {building_output_filepath}")

        hv_mv_transformer_capacity = self.config["transformers"]["mv_hv"]["capacity_kva"]
        self.pg_graph.create_mv_graph(
            mv_lv_transformer_capacity, hv_mv_transformer_capacity
        )
        self.pg_graph.extend_graph_with_cim("graph_mv_buses")

        hv_substation_capacity: int = (
            len(self.pg_graph.labels_mv) if self.pg_graph.labels_mv is not None else 0
        ) * hv_mv_transformer_capacity
        self.pg_graph.create_hv_substation_graph(
            hv_mv_transformer_capacity, hv_substation_capacity
        )
        self.pg_graph.extend_graph_with_cim("graph_hv_buses")

    def visualize_grid(self):
        self.plotter = GridPlotter(self.pg_graph)
        map_view = self.plotter.plot_building_and_centroid_graph(
            plot_lv_edges=True, plot_mv_edges=True, plot_hv_edges=True
        )
        map_view.save(os.path.join(self.output_dir, "power_grid_map.html"))
        print("Grid visualization saved to power_grid_map.html.")

    def build_pandapower_model(self):
        pp_builder = PandapowerGridBuilder(power_grid=self.pg_graph, config=self.config)
        pp_builder.build_lv_buses_and_lines()
        pp_builder.build_mv_buses_and_lines()
        pp_builder.build_hv_buses_and_lines()
        pp_builder.build_loads_from_graph_buildings()
        pp_builder.validate_network_consistency()
        pp_builder.build_lv_mv_power_transformers()
        pp_builder.build_mv_hv_power_transformers()
        pp_builder.connect_hv_bus_to_ext_grid()
        self.pp_net = pp_builder.get_pandapower_net()

        self.pg_graph.merge_graphs()
        output_filepath = os.path.join(self.output_dir, "power_grid.graphml")
        self.pg_graph.export_to_graphml(output_filepath)
        print(f"Power grid graph exported to {output_filepath}")

    def run_power_flow(self, diagnostic=False):
        
        if diagnostic:
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
            diagnostic(self.pp_net, **diagnostic_params)
        pp.runpp(self.pp_net)

    def visualize_results(self):
        if self.plotter is None:
            self.plotter = GridPlotter(self.pg_graph)
        voltage_map = self.plotter.plot_voltage_deviations_folium(self.pp_net)
        voltage_map_output_path = os.path.join(
            self.output_dir, "voltage_deviations_map.html"
        )
        voltage_map.save(voltage_map_output_path)
        print(f"Voltage deviations map saved to {voltage_map_output_path}")


def main() -> None:
    """
    This script demonstrates the creation of a power grid graph,
    its visualization, and the building of a pandapower model.
    """
    input_file = str(datasets.get_dataset_path("buildings_inside_polygon.geojson"))
    analysis = PowerFlowAnalysis(input_file=input_file)
    analysis.run()


if __name__ == "__main__":
    main()
