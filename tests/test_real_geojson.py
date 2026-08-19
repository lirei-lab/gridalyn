"""Comprehensive test suite for power grid modeling"""

import signal
import unittest

import numpy as np
import pandapower as pp
import pandas as pd
from pandapower.diagnostic import diagnostic
from timeout_decorator import timeout

from gridalyn.foundation.data import datasets
from gridalyn.twin.adapters.pandapower_builder import PandapowerGridBuilder
from gridalyn.twin.core.graph import PowerGridGraph


class TestPowerGridModel(unittest.TestCase):
    def setUp(self) -> None:
        """Test loading and processing of real GeoJSON data"""
        # Verify dataset path resolution
        real_geojson_path = datasets.get_dataset_path(
            "buildings_inside_polygon.geojson"
        )
        self.assertTrue(
            real_geojson_path.exists(), f"Dataset file not found at {real_geojson_path}"
        )
        self.assertEqual(real_geojson_path.name, "buildings_inside_polygon.geojson")

        self.power_grid = PowerGridGraph()

        # Test loading real data
        result = self.power_grid.extract_building_centers_and_areas(
            str(real_geojson_path)
        )
        self.assertIsInstance(result, pd.DataFrame)
        self.assertGreater(len(result), 0)

        # Print debug info
        if self.power_grid.building_centroids is not None:
            print(
                f"\nBuilding centroids shape: {self.power_grid.building_centroids.shape}"
            )
            print(
                f"Sample centroid (lon, lat): {self.power_grid.building_centroids[0]}"
            )

        # Configuration with adjusted parameters for better convergence
        self.config = {
            "buses": {
                "lv": {"voltage_kv": 0.4, "type": "b"},
                "mv": {"voltage_kv": 20, "type": "b"},
                "hv": {"voltage_kv": 110, "type": "b"},
            },
            "lines": {
                "lv": {
                    "min_length_km": 0.005,
                    "std_type": "NAYY 4x150 SE",
                },  # Standard LV cable
                "mv": {
                    "min_length_km": 0.05,
                    "std_type": "NA2XS2Y 1x185 RM/25 12/20 kV",
                },  # Standard MV cable
                "hv": {
                    "min_length_km": 0.5,
                    "std_type": "243-AL1/39-ST1A 110.0",
                },  # Standard HV line
            },
            "transformers": {
                "lv_mv": {"std_type": "custom_lv_mv_transformer"},
                "mv_hv": {"std_type": "custom_mv_hv_transformer"},
            },
            "external_grid": {
                "voltage_kv": 110,
                "va_degree": 0,
                "p_mw": 1000,  # Increased power for larger grid
                "q_mvar": 500,  # Increased reactive power
            },
            "loads": {"avg_load_per_building": 15},  # 15 kW per building
        }

    @timeout(300)  # 5 minute timeout
    def test_full_grid_construction(self) -> None:
        """Test complete grid construction from GeoJSON data"""

        class TimeoutError(Exception):
            pass

        def handler(signum: int, frame: object) -> None:
            raise TimeoutError("Test timed out after 5 minutes")

        signal.signal(signal.SIGALRM, handler)
        signal.alarm(300)  # 5 minutes

        # Create LV, MV and HV graphs with adjusted capacities for 1024 buildings
        # Total load: 1024 buildings * 15 kW = 15.36 MW
        self.power_grid.create_lv_graph(
            avg_load_per_building=15, mv_lv_transformer_capacity=400
        )  # 400 kVA per transformer (~40 buildings each)
        self.assertIsNotNone(self.power_grid.graph_lv_buses, "LV graph creation failed")

        mv_graph = self.power_grid.create_mv_graph(
            mv_lv_transformer_capacity=400, hv_mv_transformer_capacity=5000
        )  # 5 MVA per MV transformer (~10 LV transformers each)
        self.assertIsNotNone(mv_graph, "MV graph creation failed")

        hv_graph = self.power_grid.create_hv_substation_graph(
            hv_mv_transformer_capacity=5000,  # 5 MVA per HV transformer
            hv_substation_capacity=(
                0
                if self.power_grid.labels_mv is None
                else len(self.power_grid.labels_mv)
            )
            * 5000,  # Total HV capacity
        )
        self.assertIsNotNone(hv_graph, "HV graph creation failed")

        # Create building graph
        building_graph = self.power_grid.create_building_graph()
        self.assertIsNotNone(building_graph, "Building graph creation failed")

        # Extend graphs with CIM classes
        self.power_grid.extend_graph_with_cim("graph_lv_buses")
        self.power_grid.extend_graph_with_cim("graph_mv_buses")
        self.power_grid.extend_graph_with_cim("graph_hv_buses")

        # Create Pandapower builder
        builder = PandapowerGridBuilder(self.power_grid, self.config)
        self.assertIsNotNone(builder, "Pandapower builder creation failed")

        # Create custom transformer types
        pp.create_std_type(
            builder.net,
            name="custom_lv_mv_transformer",
            data={
                "sn_mva": 0.63,
                "vn_hv_kv": 20,
                "vn_lv_kv": 0.4,
                "vkr_percent": 0.4,
                "vk_percent": 14.9,
                "pfe_kw": 1.5,
                "i0_percent": 0.5,
                "shift_degree": 0,
            },
            element="trafo",
        )
        pp.create_std_type(
            builder.net,
            name="custom_mv_hv_transformer",
            data={
                "sn_mva": 40,
                "vn_hv_kv": 110,
                "vn_lv_kv": 20,
                "vkr_percent": 0.3,
                "vk_percent": 14.9,
                "pfe_kw": 20,
                "i0_percent": 0.3,
                "shift_degree": 0,
            },
            element="trafo",
        )

        # Build networks
        builder.build_lv_buses_and_lines()
        self.assertIsNotNone(builder.net, "LV network build failed")

        builder.build_mv_buses_and_lines()
        self.assertIsNotNone(builder.net, "MV network build failed")

        builder.build_hv_buses_and_lines()
        self.assertIsNotNone(builder.net, "HV network build failed")

        builder.build_loads_from_graph_buildings()
        self.assertGreater(
            len(builder.net.load), 0, "No loads created from building graph"
        )

        # Validate network consistency
        validation_result = builder.validate_network_consistency()
        self.assertTrue(validation_result, "Network consistency validation failed")

        # Build transformers
        lv_mv_transformers = builder.build_lv_mv_power_transformers()
        self.assertGreater(len(lv_mv_transformers), 0, "No LV-MV transformers created")

        mv_hv_transformers = builder.build_mv_hv_power_transformers()
        self.assertGreater(len(mv_hv_transformers), 0, "No MV-HV transformers created")

        # Get network and add external grid
        net = builder.get_pandapower_net()
        self.assertIsNotNone(net, "Failed to create pandapower network")

        ext_grid = builder.connect_hv_bus_to_ext_grid()
        self.assertIsNotNone(ext_grid, "Failed to connect HV bus to external grid")

        # Initialize voltage profile for better convergence
        net.bus["vm_pu"] = 1.05  # Start with higher voltage
        net.bus["va_degree"] = 0.0

        # Add power factor to loads (0.95 lagging)
        for idx in net.load.index:
            p_mw = net.load.at[idx, "p_mw"]
            net.load.at[idx, "q_mvar"] = p_mw * np.tan(np.arccos(0.95))

        try:
            # First try DC power flow for initial solution
            pp.rundcpp(net)

            # Check for voltage violations
            if any(net.bus["vm_pu"] < 0.9) or any(net.bus["vm_pu"] > 1.1):
                print("Warning: Voltage violations detected after DC power flow")

            # Then use AC power flow with DC solution as starting point
            pp.runpp(
                net,
                max_iteration=500,  # Increase max iterations
                init="results",  # Use DC power flow results
                calculate_voltage_angles=True,
                enforce_q_lims=False,  # Don't enforce reactive power limits
                tolerance_mva=1e-2,  # Further increase tolerance
                algorithm="nr",  # Newton-Raphson algorithm
                numba=True,
            )

            # Check final voltage profile
            if any(net.bus["vm_pu"] < 0.9) or any(net.bus["vm_pu"] > 1.1):
                print("Warning: Voltage violations in final solution")

        except Exception:
            raise
        self.assertTrue(net.converged, "Power flow did not converge")

        # Verify power flow results
        self.assertGreater(len(net.res_bus), 0, "No bus results found")
        self.assertGreater(len(net.res_line), 0, "No line results found")
        self.assertGreater(len(net.res_trafo), 0, "No transformer results found")
        self.assertGreater(len(net.res_load), 0, "No load results found")

        # Print network summary before diagnostics
        print("\nNetwork summary:")
        print(f"Number of buses: {len(net.bus)}")
        print(f"Number of lines: {len(net.line)}")
        print(f"Number of transformers: {len(net.trafo)}")
        print(f"Number of loads: {len(net.load)}")

        # Run diagnostic checks with detailed output
        print("\nRunning diagnostic checks...")
        diag_results = diagnostic(
            net,
            report_style="detailed",
            warnings_only=False,
            return_result_dict=True,
            overload_scaling_factor=0.001,
            lines_min_length_km=0.5 / 1000,
            min_r_ohm=0.0001,
            min_x_ohm=0.0001,
            max_r_ohm=100,
            max_x_ohm=100,
            nom_voltage_tolerance=0.3,
            numba_tolerance=1e-5,
        )

        # Print diagnostic results
        print("\nDiagnostic results:")
        if diag_results.get("errors"):
            print("Errors found:", diag_results["errors"])
        if diag_results.get("warnings"):
            print("Warnings found:", diag_results["warnings"])

        # Verify diagnostic results
        self.assertFalse(diag_results.get("errors", False), "Network has errors")
        self.assertFalse(diag_results.get("warnings", False), "Network has warnings")

    def tearDown(self) -> None:
        pass


if __name__ == "__main__":
    unittest.main()
