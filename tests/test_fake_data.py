# noqa: B950
"""Tests for generated/fake GeoJSON data processing"""

import json
import os
import tempfile
import unittest

import pandas as pd

from gridalyn.adapters.geojson import FakeGeoJSONGenerator
from gridalyn.core.graph import PowerGridGraph


class TestFakeDataProcessing(unittest.TestCase):
    def setUp(self) -> None:
        print("\nSetting up test data...")
        generator = FakeGeoJSONGenerator()
        geojson_data = generator.generate_geojson()
        print(f"Generated GeoJSON with {len(geojson_data['features'])} features")
        print(
            "Feature types:",
            [f["properties"].get("type") for f in geojson_data["features"]],
        )

        self.test_geojson = json.dumps(geojson_data)
        self.temp_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".geojson", delete=False
        )
        self.temp_file.write(self.test_geojson)
        self.temp_file.close()
        print(f"Wrote GeoJSON to temporary file: {self.temp_file.name}")

    def tearDown(self) -> None:
        os.unlink(self.temp_file.name)

    def test_geojson_loading(self) -> None:
        """Test loading and processing of generated GeoJSON data"""
        print("\nTesting GeoJSON loading...")
        pg = PowerGridGraph()
        result = pg.extract_building_centers_and_areas(self.temp_file.name)

        print(f"Extracted {len(result)} buildings")
        print("DataFrame columns:", result.columns.tolist())
        print("First few rows:", result.head())

        # Verify basic structure
        self.assertIsInstance(result, pd.DataFrame)
        self.assertEqual(
            len(result),
            1024,
            f"Expected 1024 buildings (32x32 grid) but got {len(result)}",
        )
        self.assertIn("Building ID", result.columns)
        self.assertIn("Longitude", result.columns)
        self.assertIn("Latitude", result.columns)
        self.assertIn("Area (sq. meters)", result.columns)

        # Verify data types
        self.assertTrue(result["Longitude"].dtype == "float64")
        self.assertTrue(result["Latitude"].dtype == "float64")
        self.assertTrue(result["Area (sq. meters)"].dtype == "float64")

    def test_graph_creation(self) -> None:
        """Test creation of LV, MV and HV graphs with generated data"""
        print("\nTesting graph creation...")
        pg = PowerGridGraph()
        pg.extract_building_centers_and_areas(self.temp_file.name)
        centroid_count = (
            0 if pg.building_centroids is None else len(pg.building_centroids)
        )
        print(f"Extracted {centroid_count} building centroids")

        # Test LV graph creation
        print("\nCreating LV graph...")
        pg.create_lv_graph(avg_load_per_building=10, mv_lv_transformer_capacity=100)
        self.assertIsNotNone(pg.graph_lv_buses)
        print(
            f"Created LV graph with {len(pg.graph_lv_buses.nodes) if pg.graph_lv_buses else 0} nodes and "  # noqa: B950
            f"{len(pg.graph_lv_buses.edges) if pg.graph_lv_buses else 0} edges"  # noqa: B950
        )
        print(
            "LV node types:",
            set(
                data.get("type")
                for _, data in (
                    pg.graph_lv_buses.nodes(data=True) if pg.graph_lv_buses else []
                )
            ),
        )

        # Test MV graph creation
        print("\nCreating MV graph...")
        mv_graph = pg.create_mv_graph(
            mv_lv_transformer_capacity=100, hv_mv_transformer_capacity=1000
        )
        self.assertIsNotNone(mv_graph)
        print(
            f"Created MV graph with {len(mv_graph.nodes)} nodes and "
            f"{len(mv_graph.edges)} edges"
        )
        print(
            "MV node types:",
            set(data.get("type") for _, data in mv_graph.nodes(data=True)),
        )

        # Test HV graph creation
        print("\nCreating HV graph...")
        hv_graph = pg.create_hv_substation_graph(
            hv_mv_transformer_capacity=1000, hv_substation_capacity=10000
        )
        self.assertIsNotNone(hv_graph)
        print(
            f"Created HV graph with {len(hv_graph.nodes)} nodes and "
            f"{len(hv_graph.edges)} edges"
        )
        print(
            "HV node types:",
            set(data.get("type") for _, data in hv_graph.nodes(data=True)),
        )

    def test_isolated_nodes(self) -> None:
        """Test that there are no isolated nodes in the merged graph"""
        print("\nTesting for isolated nodes...")
        pg = PowerGridGraph()
        pg.extract_building_centers_and_areas(self.temp_file.name)
        centroid_count = (
            0 if pg.building_centroids is None else len(pg.building_centroids)
        )
        print(f"Extracted {centroid_count} building centroids")

        print("\nCreating graphs...")
        pg.create_lv_graph(avg_load_per_building=10, mv_lv_transformer_capacity=100)
        print(
            f"Created LV graph with {len(pg.graph_lv_buses.nodes) if pg.graph_lv_buses else 0} nodes and "  # noqa: B950
            f"{len(pg.graph_lv_buses.edges) if pg.graph_lv_buses else 0} edges"  # noqa: B950
        )

        pg.create_mv_graph(
            mv_lv_transformer_capacity=100, hv_mv_transformer_capacity=1000
        )
        print(
            f"Created MV graph with {len(pg.graph_mv_buses.nodes) if pg.graph_mv_buses else 0} nodes and "  # noqa: B950
            f"{len(pg.graph_mv_buses.edges) if pg.graph_mv_buses else 0} edges"  # noqa: B950
        )

        pg.create_hv_substation_graph(
            hv_mv_transformer_capacity=1000, hv_substation_capacity=10000
        )
        print(
            f"Created HV graph with {len(pg.graph_hv_buses.nodes) if pg.graph_hv_buses else 0} nodes and "  # noqa: B950
            f"{len(pg.graph_hv_buses.edges) if pg.graph_hv_buses else 0} edges"  # noqa: B950
        )

        print("\nMerging graphs...")
        merged_graph = pg.merge_graphs()
        print(
            f"Created merged graph with {len(merged_graph.nodes)} nodes and "
            f"{len(merged_graph.edges)} edges"
        )

        # Check for isolated nodes
        print("\nChecking for isolated nodes...")
        isolated_nodes = pg.check_for_isolated_nodes()
        for graph_name, nodes in isolated_nodes.items():
            print(f"{graph_name}: {len(nodes or [])} isolated nodes")
            if nodes:
                print(f"Isolated nodes in {graph_name}: {nodes}")

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

    def test_graph_merging(self) -> None:
        """Test merging of all graphs with generated data"""
        print("\nTesting graph merging...")
        pg = PowerGridGraph()
        pg.extract_building_centers_and_areas(self.temp_file.name)
        centroid_count = (
            0 if pg.building_centroids is None else len(pg.building_centroids)
        )
        print(f"Extracted {centroid_count} building centroids")

        print("\nCreating individual graphs...")
        pg.create_lv_graph(avg_load_per_building=10, mv_lv_transformer_capacity=100)
        print(
            f"Created LV graph with {len(pg.graph_lv_buses.nodes) if pg.graph_lv_buses else 0} nodes and "  # noqa: B950
            f"{len(pg.graph_lv_buses.edges) if pg.graph_lv_buses else 0} edges"  # noqa: B950
        )

        pg.create_mv_graph(
            mv_lv_transformer_capacity=100, hv_mv_transformer_capacity=1000
        )
        print(
            f"Created MV graph with {len(pg.graph_mv_buses.nodes) if pg.graph_mv_buses else 0} nodes and "  # noqa: B950
            f"{len(pg.graph_mv_buses.edges) if pg.graph_mv_buses else 0} edges"  # noqa: B950
        )

        pg.create_hv_substation_graph(
            hv_mv_transformer_capacity=1000, hv_substation_capacity=10000
        )
        print(
            f"Created HV graph with {len(pg.graph_hv_buses.nodes) if pg.graph_hv_buses else 0} nodes and "  # noqa: B950
            f"{len(pg.graph_hv_buses.edges) if pg.graph_hv_buses else 0} edges"  # noqa: B950
        )

        print("\nMerging graphs...")
        merged_graph = pg.merge_graphs()
        self.assertIsNotNone(merged_graph)
        print(
            f"Created merged graph with {len(merged_graph.nodes)} nodes and "
            f"{len(merged_graph.edges)} edges"
        )

        # Verify transformer connections exist
        transformer_edges = [
            (u, v)
            for u, v, d in merged_graph.edges(data=True)
            if d.get("cimclass") == "cim.PowerTransformer"
        ]
        print(f"\nFound {len(transformer_edges)} transformer connections:")
        print(
            "LV-MV transformers:",
            [
                edge
                for edge in transformer_edges
                if "lv_feeder" in edge[0] or "lv_feeder" in edge[1]
            ],
        )
        print(
            "MV-HV transformers:",
            [
                edge
                for edge in transformer_edges
                if "mv_feeder" in edge[0] or "mv_feeder" in edge[1]
            ],
        )

        self.assertGreater(
            len(transformer_edges),
            0,
            "No transformer connections found in merged graph",
        )


if __name__ == "__main__":
    unittest.main()
