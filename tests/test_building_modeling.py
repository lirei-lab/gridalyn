import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from gridalyn.assets.modeling import (
    load_base_inputs,
    synthesize_building_model_tables,
    write_building_model_artifacts,
)


class BuildingModelingTest(unittest.TestCase):
    def _sample_buildings(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "building_id": "building:1",
                    "load_id": "load:1",
                    "lv_bus_id": "bus:1",
                    "area_m2": 95.0,
                    "static_p_mw": 0.008,
                    "load_seed_base": 101,
                    "thermal_seed_base": 201,
                    "has_ev": False,
                    "ev_id": None,
                    "scenario_id": "BASE",
                },
                {
                    "building_id": "building:2",
                    "load_id": "load:2",
                    "lv_bus_id": "bus:2",
                    "area_m2": 420.0,
                    "static_p_mw": 0.018,
                    "load_seed_base": 102,
                    "thermal_seed_base": 202,
                    "has_ev": True,
                    "ev_id": "ev:2",
                    "scenario_id": "S4",
                },
            ]
        )

    def _sample_connectivity(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "building_id": "building:1",
                    "load_id": "load:1",
                    "load_bus_id": "bus:1",
                    "lv_cluster": 7,
                    "lv_feeder_bus_id": "bus:100",
                    "lv_transformer_id": "transformer:7",
                    "connectivity_status": "ok",
                },
                {
                    "building_id": "building:2",
                    "load_id": "load:2",
                    "load_bus_id": "bus:2",
                    "lv_cluster": 8,
                    "lv_feeder_bus_id": "bus:101",
                    "lv_transformer_id": "transformer:8",
                    "connectivity_status": "ok",
                },
            ]
        )

    def test_synthesis_creates_pycity_style_entity_tables(self):
        tables = synthesize_building_model_tables(
            self._sample_buildings(),
            connectivity=self._sample_connectivity(),
            profile="north_america_residential_v1",
        )

        self.assertEqual(
            set(tables),
            {"building_models", "thermal_zones", "device_registry", "end_use_loads"},
        )
        self.assertEqual(len(tables["building_models"]), 2)
        self.assertEqual(len(tables["thermal_zones"]), 2)
        self.assertEqual(len(tables["end_use_loads"]), 6)

        model = tables["building_models"].set_index("building_id")
        self.assertEqual(
            model.loc["building:1", "archetype_id"], "na_residential_small"
        )
        self.assertEqual(
            model.loc["building:2", "archetype_id"], "na_residential_multifamily"
        )
        self.assertEqual(model.loc["building:2", "lv_transformer_id"], "transformer:8")
        self.assertGreater(model.loc["building:1", "heating_capacity_kw"], 0.0)
        self.assertGreater(model.loc["building:1", "thermal_resistance_c_per_kw"], 0.0)

        devices = tables["device_registry"]
        self.assertIn("hvac_heating", set(devices["device_type"]))
        self.assertIn("hvac_cooling", set(devices["device_type"]))
        self.assertIn("evse_l2", set(devices["device_type"]))
        self.assertEqual(
            len(
                devices[
                    (devices["building_id"] == "building:2")
                    & (devices["device_type"] == "evse_l2")
                ]
            ),
            1,
        )

    def test_write_building_model_artifacts_writes_manifest_and_parquet(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "instances" / "default" / "digital_twin" / "models"
            manifest = write_building_model_artifacts(
                buildings=self._sample_buildings(),
                connectivity=self._sample_connectivity(),
                out_dir=out_dir,
                root=Path(tmpdir),
            )

            self.assertEqual(manifest["model_profile"], "north_america_residential_v1")
            self.assertEqual(manifest["counts"]["building_models"], 2)
            self.assertEqual(manifest["counts"]["evse_devices"], 1)
            self.assertTrue((out_dir / "building_models.parquet").exists())
            self.assertTrue((out_dir / "thermal_zones.parquet").exists())
            self.assertTrue((out_dir / "device_registry.parquet").exists())
            self.assertTrue((out_dir / "end_use_loads.parquet").exists())

            saved = json.loads((out_dir / "building_model_manifest.json").read_text())
            self.assertEqual(
                saved["artifacts"]["building_models"],
                "instances/default/digital_twin/models/building_models.parquet",
            )
            self.assertEqual(saved["counts"]["building_models"], 2)

    def test_load_base_inputs_uses_network_repository(self):
        class FakeModel:
            buildings = self._sample_buildings()
            connectivity = self._sample_connectivity()

        class FakeRepository:
            @classmethod
            def from_parquet(cls, base_dir):
                self = cls()
                self.base_dir = base_dir
                return self

            def load_model(self):
                return FakeModel()

        with (
            patch(
                "gridalyn.assets.modeling.artifacts.NetworkModelRepository",
                FakeRepository,
                create=True,
            ),
            patch.object(
                pd, "read_parquet", side_effect=AssertionError("raw base parquet read")
            ),
        ):
            buildings, connectivity = load_base_inputs(
                Path("instances/default/digital_twin/base")
            )

        self.assertEqual(list(buildings["building_id"]), ["building:1", "building:2"])
        self.assertIsNotNone(connectivity)
        self.assertEqual(
            list(connectivity["lv_transformer_id"]), ["transformer:7", "transformer:8"]
        )


if __name__ == "__main__":
    unittest.main()
