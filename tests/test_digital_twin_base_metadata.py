import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from gridalyn.projects.workflows.digital_twin.base_metadata import build_base_metadata, write_base_metadata


class DigitalTwinBaseMetadataTest(unittest.TestCase):
    def _write_base_model(self, base: Path) -> None:
        pd.DataFrame(
            [
                {"bus_id": "bus:0", "category": "MV"},
                {"bus_id": "bus:1", "category": "LV"},
            ]
        ).to_parquet(base / "grid_buses.parquet")
        pd.DataFrame(
            [{"line_id": "line:0", "from_bus_id": "bus:0", "to_bus_id": "bus:1"}]
        ).to_parquet(base / "grid_lines.parquet")
        pd.DataFrame(
            [{"transformer_id": "transformer:0", "hv_bus_id": "bus:0", "lv_bus_id": "bus:1"}]
        ).to_parquet(base / "grid_transformers.parquet")
        pd.DataFrame(
            [{"building_id": "building:0", "load_id": "load:0", "lv_bus_id": "bus:1"}]
        ).to_parquet(base / "buildings.parquet")
        pd.DataFrame(
            [{"building_id": "building:0", "load_id": "load:0", "load_bus_id": "bus:1"}]
        ).to_parquet(base / "building_grid_connectivity.parquet")

    def test_builds_repository_centric_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "instances" / "default" / "digital_twin" / "base"
            base.mkdir(parents=True)
            self._write_base_model(base)

            metadata = build_base_metadata(
                base_dir=base,
                root=root,
                config_path=root / "config.json",
                config_hash="abc123",
                cache_dir=root / "cache",
                source_adapter="SyntheticPandapowerAdapter",
                adapter_validation_report=root / "reports" / "network_adapter_validation_report.json",
            )

        self.assertEqual(metadata["schema_version"], "1.0")
        self.assertEqual(metadata["source_adapter"], "SyntheticPandapowerAdapter")
        self.assertEqual(metadata["source_standard"], "pandapower")
        self.assertTrue(metadata["model_version"]["id"].startswith("model:sha256:"))
        self.assertEqual(metadata["model_version_id"], metadata["model_version"]["id"])
        self.assertEqual(metadata["model_version"]["source_adapter"], "SyntheticPandapowerAdapter")
        self.assertEqual(metadata["model_version"]["source_standard"], "pandapower")
        self.assertEqual(metadata["model_version"]["validation_status"], "valid")
        self.assertIn("grid_buses", metadata["model_version"]["artifact_hashes"])
        self.assertEqual(metadata["counts"]["buses"], 2)
        self.assertEqual(metadata["counts"]["loads"], 1)
        self.assertTrue(metadata["validation"]["valid"])
        self.assertIn("grid_buses", metadata["artifacts"])
        self.assertEqual(metadata["artifacts"]["grid_buses"]["row_count"], 2)
        self.assertTrue(metadata["artifacts"]["grid_buses"]["sha256"])
        self.assertEqual(
            metadata["adapter_validation_report"],
            "reports/network_adapter_validation_report.json",
        )

    def test_write_base_metadata_materializes_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "instances" / "default" / "digital_twin" / "base"
            base.mkdir(parents=True)
            self._write_base_model(base)

            path = write_base_metadata(
                base_dir=base,
                root=root,
                config_path=root / "config.json",
                config_hash="abc123",
                cache_dir=root / "cache",
            )

            metadata = json.loads(path.read_text())

        self.assertEqual(path.name, "metadata.json")
        self.assertEqual(metadata["counts"]["buildings"], 1)
        self.assertEqual(metadata["validation"]["errors"], [])


if __name__ == "__main__":
    unittest.main()
