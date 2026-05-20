"""Tests for the datasets module."""

import shutil
import tempfile
import unittest
from pathlib import Path

from gridalyn.foundation.data import datasets


class DatasetAccessTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_data_dir = Path(tempfile.mkdtemp())
        (self.temp_data_dir / "test1.geojson").touch()
        (self.temp_data_dir / "test2.csv").touch()
        self.original_example_data_dir = datasets.EXAMPLE_DATA_DIR
        self.original_package_data_dir = datasets.PACKAGE_DATA_DIR
        datasets.EXAMPLE_DATA_DIR = self.temp_data_dir
        datasets.PACKAGE_DATA_DIR = self.temp_data_dir

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_data_dir)
        datasets.EXAMPLE_DATA_DIR = self.original_example_data_dir
        datasets.PACKAGE_DATA_DIR = self.original_package_data_dir

    def test_get_dataset_path_exists(self) -> None:
        path = datasets.get_dataset_path("test1.geojson")

        self.assertTrue(path.exists())
        self.assertEqual(path.name, "test1.geojson")
        self.assertTrue(str(path).startswith(str(self.temp_data_dir)))

    def test_public_dataset_access(self) -> None:
        datasets.EXAMPLE_DATA_DIR = self.original_example_data_dir
        datasets.PACKAGE_DATA_DIR = self.original_package_data_dir
        path = datasets.get_dataset_path("buildings_inside_polygon.geojson")

        self.assertTrue(path.exists())
        self.assertEqual(path.name, "buildings_inside_polygon.geojson")
        self.assertIn("examples/tutorials/data", path.as_posix())

    def test_lists_example_datasets(self) -> None:
        datasets.EXAMPLE_DATA_DIR = self.original_example_data_dir
        datasets.PACKAGE_DATA_DIR = self.original_package_data_dir
        names = datasets.list_available_datasets()

        self.assertIn("buildings_inside_polygon.geojson", names)
        self.assertIn("example_buildings.geojson", names)
        self.assertNotIn("data_usage_instructions.md", names)
        self.assertNotIn("datasets.py", names)

    def test_dataset_discovery_has_no_class_based_compatibility_stubs(self) -> None:
        self.assertFalse(hasattr(datasets, "PowerGridDataset"))
        self.assertFalse(hasattr(datasets, "CIMDataset"))
        self.assertFalse(hasattr(datasets, "GeoJSONDataset"))


if __name__ == "__main__":
    unittest.main()
