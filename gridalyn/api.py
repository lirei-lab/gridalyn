import logging
from typing import Any, Dict, Optional

from gridalyn.twin.core.graph import PowerGridGraph
from gridalyn.interfaces.viz.interactive import GridPlotter


class Interface:
    """Interface for performing power grid operations."""

    def __init__(self, config: Optional[Dict[str, Any]] = None, logger: Optional[logging.Logger] = None):
        """Initializes the Interface for power grid operations.

        Args:
            config (Optional[Dict[str, Any]]): A dictionary containing configuration
                parameters for the power grid analysis. If None, default is used.
            logger (Optional[logging.Logger]): A logger instance. If not
                provided, a new one will be created.
        """
        if logger is None:
            self.logger = logging.getLogger(__name__)
            self.logger.setLevel(logging.INFO)
        else:
            self.logger = logger
        self.logger.info("Initializing Graph Interface")
        self.power_grid: Optional[PowerGridGraph] = None
        self.plotter: Optional[GridPlotter] = None
        
        default_config = {
            "loads": {
                "max_load_per_building": 25.0,
                "diversity_factor_lv": 5.0,
                "diversity_factor_mv": 1.3,
                "diversity_factor_hv": 1.1
            },
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
                "lv_mv": {"std_type": "0.63 MVA 20/0.4 kV", "capacity_kva": 250, "utilization_margin": 0.80},
                "mv_hv": {"std_type": "25 MVA 110/20 kV", "capacity_kva": 25000},
            },
        }
        self.config: Dict[str, Any] = config if config is not None else default_config
        self.net = None

    def extract_building_data(self, input_file: str) -> bool:
        """Extracts building data from a GeoJSON file."""
        self.logger.info(f"Extracting building data from {input_file}")
        try:
            self.power_grid = PowerGridGraph()
            self.power_grid.logger = self.logger
            self.power_grid.extract_building_centers_and_areas(input_file)
            self.logger.info("Building data extracted successfully!")
            return True
        except Exception as e:
            self.logger.error(f"Error extracting building data: {str(e)}")
            return False

    def create_grid_graphs(self) -> bool:
        """Creates the LV, MV, and HV graphs."""
        self.logger.info("Creating grid graphs")
        if self.power_grid is None:
            self.logger.error("Power grid not initialized. Cannot create graphs.")
            return False
        try:
            max_load_per_building = self.config["loads"]["max_load_per_building"]
            diversity_factor_lv = self.config["loads"].get("diversity_factor_lv", 5.0)
            diversity_factor_mv = self.config["loads"].get("diversity_factor_mv", 1.3)
            diversity_factor_hv = self.config["loads"].get("diversity_factor_hv", 1.1)
            
            lv_transformer_config = self.config["transformers"]["lv_mv"]
            mv_lv_transformer_capacity = lv_transformer_config.get("capacity_kva", 250)
            mv_lv_sizing_capacity = lv_transformer_config.get(
                "sizing_capacity_kva", mv_lv_transformer_capacity
            )
            capacity_utilization_factor = lv_transformer_config.get("utilization_margin", 0.80)
            
            self.power_grid.create_lv_graph(
                max_load_per_building, 
                mv_lv_sizing_capacity,
                capacity_utilization_factor,
                diversity_factor_lv
            )
            self.power_grid.extend_graph_with_cim("graph_lv_buses")
            
            # Note: pass it here
            self.power_grid.create_building_graph(max_load_per_building=max_load_per_building, diversity_factor_lv=diversity_factor_lv)

            hv_mv_transformer_capacity = self.config["transformers"]["mv_hv"].get(
                "capacity_kva", 25000
            )
            mv_hv_transformer_count = self.config["transformers"]["mv_hv"].get(
                "count", None
            )
            self.power_grid.create_mv_graph(
                mv_lv_sizing_capacity,
                hv_mv_transformer_capacity,
                diversity_factor_mv,
                num_mv_substations=mv_hv_transformer_count,
            )
            self.power_grid.extend_graph_with_cim("graph_mv_buses")

            num_mv_labels = (
                len(self.power_grid.labels_mv)
                if self.power_grid.labels_mv is not None
                else 0
            )
            # Add basic mapping for HV Substation load aggregation check 
            hv_substation_capacity = num_mv_labels * hv_mv_transformer_capacity
            self.power_grid.create_hv_substation_graph(
                hv_mv_transformer_capacity, hv_substation_capacity, diversity_factor_hv
            )
            self.power_grid.extend_graph_with_cim("graph_hv_buses")

            self.plotter = GridPlotter(self.power_grid)
            self.logger.info("Grid graphs created successfully!")
            return True
        except Exception as e:
            self.logger.error(f"Error creating grid graphs: {str(e)}")
            return False

    def load_grid(self, input_file: str) -> str:
        """Loads a power grid from a GeoJSON file.

        This method initializes a `PowerGridGraph`, extracts building data,
        creates the LV, MV, and HV graphs, and extends them with CIM data.

        Args:
            input_file (str): The path to the input GeoJSON file.

        Returns:
            str: A message indicating the result of the operation.
        """
        self.logger.info("Loading grid")
        if not self.extract_building_data(input_file):
            return "Error loading grid: Failed to extract building data."
        if not self.create_grid_graphs():
            return "Error loading grid: Failed to create grid graphs."

        self.logger.info("Grid loaded successfully!")
        return "Grid loaded successfully!"

    def visualize_grid(
        self, show_lv: bool = True, show_mv: bool = True, show_hv: bool = True
    ) -> Optional[str]:
        """Generates a visualization of the power grid."""
        self.logger.info("Generating grid visualization")
        if self.power_grid is None or self.plotter is None:
            self.logger.warning("Power grid or plotter not initialized")
            return None
        try:
            m = self.plotter.plot_building_and_centroid_graph(
                plot_lv_edges=show_lv, plot_mv_edges=show_mv, plot_hv_edges=show_hv
            )
            m.get_root().width = "800px"
            m.get_root().height = "600px"
            iframe = m.get_root()._repr_html_()
            self.logger.info("Grid visualization generated successfully")
            return iframe
        except Exception as e:
            self.logger.error(f"Error generating grid visualization: {str(e)}")
            return None

    def build_pp(self) -> None:
        """Builds a pandapower network."""
        self.logger.info("Building pandapower network")
        if self.power_grid is None:
            self.logger.warning("Power grid not initialized")
            return

        try:
            from pandapower.diagnostic import diagnostic
            from gridalyn.simulation.simulators.powerflow.builder import PandapowerGridBuilder

            builder = PandapowerGridBuilder(self.power_grid, self.config)
            builder.logger = self.logger
            builder.build_lv_buses_and_lines()
            builder.build_mv_buses_and_lines()
            builder.build_hv_buses_and_lines()
            builder.build_loads_from_graph_buildings()
            builder.build_lv_mv_power_transformers()
            builder.build_mv_hv_power_transformers()
            builder.connect_hv_bus_to_ext_grid()
            builder.validate_network_consistency()
            self.net = builder.get_pandapower_net()
            self.logger.info("Pandapower network built successfully")

        except Exception as e:
            self.logger.error(f"Error building pandapower network: {str(e)}")

    def run_simulation(self) -> Optional[str]:
        """Runs a power flow simulation and returns the results as an HTML map."""
        self.logger.info("Running power flow simulation")
        if self.net is None:
            self.logger.warning("Pandapower network not initialized")
            return "Pandapower network not initialized. Please build the grid first."
        try:
            import pandapower as pp

            pp.runpp(self.net, numba=True)
            if not self.net.converged:
                self.logger.warning("Power flow did not converge.")

            m = self.plotter.plot_voltage_deviations_folium(self.net)
            m.get_root().width = "800px"
            m.get_root().height = "600px"
            iframe = m.get_root()._repr_html_()
            self.logger.info("Simulation and visualization completed successfully")
            return iframe
        except Exception as e:
            self.logger.error(f"Error running simulation: {str(e)}")
            return f"Error running simulation: {str(e)}"
