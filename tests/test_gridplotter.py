"""Test suite for GridPlotter"""

import json
import logging
import tempfile
import unittest

import folium

from gridalyn.twin.adapters.geojson import FakeGeoJSONGenerator
from gridalyn.interfaces.viz.interactive import GridPlotter, PowerGridGraph

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class TestGridPlotter(unittest.TestCase):
    def setUp(self) -> None:
        logger.debug("Setting up test case")
        # Initialize fake GeoJSON generator with a small grid for faster tests
        self.generator = FakeGeoJSONGenerator(grid_size=8)  # 8x8 = 64 buildings
        logger.debug("Created FakeGeoJSONGenerator")

        # Initialize PowerGridGraph
        self.power_grid = PowerGridGraph()

        # Generate GeoJSON and save to temporary file
        geojson = self.generator.generate_geojson()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".geojson", delete=False
        ) as f:
            json.dump(geojson, f)
            self.temp_geojson_path = f.name
            f.flush()

        # Extract building data
        self.power_grid.extract_building_centers_and_areas(self.temp_geojson_path)

        # Create grid hierarchy with reasonable capacities for 64 buildings
        # Total load: 64 buildings * 10 kW = 640 kW
        self.power_grid.create_lv_graph(
            avg_load_per_building=10,  # 10 kW per building
            mv_lv_transformer_capacity=200,  # 200 kVA per transformer (~20 buildings each)
        )

        self.power_grid.create_mv_graph(
            mv_lv_transformer_capacity=200,  # 200 kVA per LV transformer
            hv_mv_transformer_capacity=1000,  # 1 MVA per MV transformer
        )

        self.power_grid.create_hv_substation_graph(
            hv_mv_transformer_capacity=1000,  # 1 MVA per HV transformer
            hv_substation_capacity=2000,  # 2 MVA total HV capacity
        )

        # Create building graph
        self.power_grid.create_building_graph()

    def test_gridplotter_initialization(self) -> None:
        """Test GridPlotter initialization"""
        logger.debug("Testing GridPlotter initialization")
        plotter = GridPlotter(self.power_grid)
        logger.debug("Created GridPlotter instance")
        self.assertEqual(plotter.power_grid, self.power_grid)

    def test_plot_building_and_centroid_graph_all_layers(self) -> None:
        """Test plotting with all layers enabled"""
        logger.debug("Testing plot with all layers")
        plotter = GridPlotter(self.power_grid)
        logger.debug("Created GridPlotter instance")
        map_obj = plotter.plot_building_and_centroid_graph(
            plot_lv_edges=True, plot_mv_edges=True, plot_hv_edges=True
        )

        # Verify the returned object is a Folium map
        self.assertIsInstance(map_obj, folium.Map)

        # Check if all expected feature groups are present
        feature_group_names = set()
        for child in map_obj._children.values():
            if isinstance(child, folium.FeatureGroup):
                feature_group_names.add(child.layer_name)

        expected_groups = {
            "LV Buses",
            "MV Buses",
            "HV Buses",
            "LV Lines",
            "MV Lines",
            "HV Lines",
        }
        self.assertEqual(feature_group_names, expected_groups)

        # PowerGridGraph stores node coordinates as x=longitude, y=latitude.
        # Folium map locations must be [latitude, longitude].
        lv_nodes = [data for _, data in self.power_grid.graph_lv_buses.nodes(data=True)]
        expected_lat = sum(node["y"] for node in lv_nodes) / len(lv_nodes)
        expected_lon = sum(node["x"] for node in lv_nodes) / len(lv_nodes)
        self.assertAlmostEqual(map_obj.location[0], expected_lat)
        self.assertAlmostEqual(map_obj.location[1], expected_lon)

    def test_plot_building_and_centroid_graph_no_edges(self) -> None:
        """Test plotting with all edge layers disabled"""
        logger.debug("Testing plot with no edges")
        plotter = GridPlotter(self.power_grid)
        logger.debug("Created GridPlotter instance")
        map_obj = plotter.plot_building_and_centroid_graph(
            plot_lv_edges=False, plot_mv_edges=False, plot_hv_edges=False
        )

        # Check feature groups - should only have bus layers
        feature_group_names = set()
        for child in map_obj._children.values():
            if isinstance(child, folium.FeatureGroup):
                feature_group_names.add(child.layer_name)

        expected_groups = {"LV Buses", "MV Buses", "HV Buses"}
        self.assertTrue(all(group in feature_group_names for group in expected_groups))
        self.assertFalse(
            any(
                group in feature_group_names
                for group in ["LV Lines", "MV Lines", "HV Lines"]
            )
        )

    def test_plot_building_and_centroid_graph_partial_edges(self) -> None:
        """Test plotting with some edge layers enabled and others disabled"""
        logger.debug("Testing plot with partial edges")
        plotter = GridPlotter(self.power_grid)
        logger.debug("Created GridPlotter instance")
        map_obj = plotter.plot_building_and_centroid_graph(
            plot_lv_edges=True, plot_mv_edges=False, plot_hv_edges=True
        )

        # Check feature groups
        feature_group_names = set()
        for child in map_obj._children.values():
            if isinstance(child, folium.FeatureGroup):
                feature_group_names.add(child.layer_name)

        # Should have all bus layers
        self.assertTrue(
            all(
                group in feature_group_names
                for group in ["LV Buses", "MV Buses", "HV Buses"]
            )
        )

        # Should have LV and HV lines but not MV lines
        self.assertTrue("LV Lines" in feature_group_names)
        self.assertTrue("HV Lines" in feature_group_names)
        self.assertFalse("MV Lines" in feature_group_names)


if __name__ == "__main__":
    unittest.main()
