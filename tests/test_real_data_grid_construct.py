"""Tests for real GeoJSON data processing"""

import unittest

import pandas as pd

from gridalyn.foundation.data import get_dataset_path
from gridalyn.twin.core.graph import PowerGridGraph


class TestRealDataProcessing(unittest.TestCase):
    def test_real_geojson_loading(self) -> None:
        """Test loading and processing of real GeoJSON data"""
        # Verify dataset path resolution
        real_geojson_path = get_dataset_path("buildings_inside_polygon.geojson")
        self.assertTrue(
            real_geojson_path.exists(), f"Dataset file not found at {real_geojson_path}"
        )
        self.assertEqual(real_geojson_path.name, "buildings_inside_polygon.geojson")

        pg = PowerGridGraph()

        # Test for missing file
        with self.assertRaises(FileNotFoundError):
            pg.extract_building_centers_and_areas("nonexistent_file.geojson")

        # Test for invalid file format
        with self.assertRaises(ValueError):
            pg.extract_building_centers_and_areas(
                __file__
            )  # Try to load this test file as GeoJSON

        # Test loading real data
        result = pg.extract_building_centers_and_areas(str(real_geojson_path))
        self.assertIsInstance(result, pd.DataFrame)
        self.assertGreater(len(result), 0)

        # Test graph creation with real data
        pg.create_lv_graph(avg_load_per_building=10, mv_lv_transformer_capacity=100)
        pg.create_mv_graph(
            mv_lv_transformer_capacity=100, hv_mv_transformer_capacity=1000
        )
        pg.create_hv_substation_graph(
            hv_mv_transformer_capacity=1000, hv_substation_capacity=10000
        )

        # Test for isolated nodes in real data
        isolated_nodes = pg.check_for_isolated_nodes()
        self.assertEqual(
            len(isolated_nodes["graph_lv_buses"] or []),
            0,
            f"Found isolated nodes in LV graph: {isolated_nodes['graph_lv_buses']}",
        )
        self.assertEqual(
            len(isolated_nodes["graph_mv_buses"] or []),
            0,
            f"Found isolated nodes in MV graph: {isolated_nodes['graph_mv_buses']}",
        )
        self.assertEqual(
            len(isolated_nodes["graph_hv_buses"] or []),
            0,
            f"Found isolated nodes in HV graph: {isolated_nodes['graph_hv_buses']}",
        )


if __name__ == "__main__":
    unittest.main()
