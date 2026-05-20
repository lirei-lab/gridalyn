import tempfile
import unittest
from pathlib import Path

import pandas as pd

from gridalyn.twin import NetworkModelRepository


class NetworkModelRepositoryTest(unittest.TestCase):
    def _write_base_model(self, base: Path) -> None:
        pd.DataFrame(
            [
                {"bus_id": "bus:source", "category": "MV"},
                {"bus_id": "bus:lv_0", "category": "LV"},
                {"bus_id": "bus:load_0", "category": "LV"},
                {"bus_id": "bus:load_1", "category": "LV"},
            ]
        ).to_parquet(base / "grid_buses.parquet")
        pd.DataFrame(
            [
                {
                    "transformer_id": "transformer:0",
                    "hv_bus_id": "bus:source",
                    "lv_bus_id": "bus:lv_0",
                }
            ]
        ).to_parquet(base / "grid_transformers.parquet")
        pd.DataFrame(
            [
                {
                    "line_id": "line:0",
                    "from_bus_id": "bus:lv_0",
                    "to_bus_id": "bus:load_0",
                },
                {
                    "line_id": "line:1",
                    "from_bus_id": "bus:load_0",
                    "to_bus_id": "bus:load_1",
                },
            ]
        ).to_parquet(base / "grid_lines.parquet")
        pd.DataFrame(
            [
                {
                    "building_id": "building:0",
                    "load_id": "load:0",
                    "lv_bus_id": "bus:load_0",
                },
                {
                    "building_id": "building:1",
                    "load_id": "load:1",
                    "lv_bus_id": "bus:load_1",
                },
            ]
        ).to_parquet(base / "buildings.parquet")
        pd.DataFrame(
            [
                {
                    "building_id": "building:0",
                    "load_id": "load:0",
                    "load_bus_id": "bus:load_0",
                    "lv_feeder_bus_id": "bus:lv_0",
                    "lv_cluster": 7,
                    "lv_transformer_id": "transformer:0",
                },
                {
                    "building_id": "building:1",
                    "load_id": "load:1",
                    "load_bus_id": "bus:load_1",
                    "lv_feeder_bus_id": "bus:lv_0",
                    "lv_cluster": 7,
                    "lv_transformer_id": "transformer:0",
                },
            ]
        ).to_parquet(base / "building_grid_connectivity.parquet")

    def test_loads_parquet_model_and_queries_downstream_transformer(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._write_base_model(base)

            repo = NetworkModelRepository.from_parquet(base)
            model = repo.load_model()
            downstream = repo.get_downstream("transformer:0")

        self.assertEqual(model.counts["buses"], 4)
        self.assertIn("building:0", downstream.building_ids)
        self.assertIn("building:1", downstream.building_ids)
        self.assertIn("load:0", downstream.load_ids)
        self.assertIn("bus:load_1", downstream.bus_ids)

    def test_queries_feeder_by_lv_feeder_bus(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._write_base_model(base)

            repo = NetworkModelRepository.from_parquet(base)
            feeder = repo.get_feeder("bus:lv_0")

        self.assertEqual(feeder.constraint_id, "bus:lv_0")
        self.assertEqual(feeder.building_ids, ("building:0", "building:1"))
        self.assertEqual(feeder.load_ids, ("load:0", "load:1"))
        self.assertEqual(feeder.bus_ids, ("bus:load_0", "bus:load_1"))

    def test_queries_equipment_connected_to_bus(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._write_base_model(base)

            repo = NetworkModelRepository.from_parquet(base)
            equipment = repo.get_connected_equipment("bus:load_0")

        self.assertEqual(equipment.bus_id, "bus:load_0")
        self.assertEqual(equipment.building_ids, ("building:0",))
        self.assertEqual(equipment.load_ids, ("load:0",))
        self.assertEqual(equipment.line_ids, ("line:0", "line:1"))
        self.assertEqual(equipment.transformer_ids, ())

    def test_validates_endpoint_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._write_base_model(base)
            pd.DataFrame(
                [{"line_id": "line:bad", "from_bus_id": "bus:load_0", "to_bus_id": "bus:missing"}]
            ).to_parquet(base / "grid_lines.parquet")

            repo = NetworkModelRepository.from_parquet(base)
            report = repo.validate_integrity()

        self.assertFalse(report.valid)
        self.assertIn("line line:bad references missing to_bus_id bus:missing", report.errors)


if __name__ == "__main__":
    unittest.main()
