import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from gridalyn.modeling import (
    synthesize_scenario_device_tables,
    write_scenario_model_artifacts,
)


def _building_models() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "model_id": "building_model:building:1",
                "building_id": "building:1",
                "load_id": "load:1",
                "load_bus_id": "bus:1",
                "lv_transformer_id": "transformer:7",
            },
            {
                "model_id": "building_model:building:2",
                "building_id": "building:2",
                "load_id": "load:2",
                "load_bus_id": "bus:2",
                "lv_transformer_id": "transformer:8",
            },
            {
                "model_id": "building_model:building:3",
                "building_id": "building:3",
                "load_id": "load:3",
                "load_bus_id": "bus:3",
                "lv_transformer_id": "transformer:8",
            },
        ]
    )


def _base_devices() -> pd.DataFrame:
    rows = []
    for building_id, model_id in [
        ("building:1", "building_model:building:1"),
        ("building:2", "building_model:building:2"),
        ("building:3", "building_model:building:3"),
    ]:
        rows.extend(
            [
                {
                    "device_id": f"device:{building_id}:hvac_heating",
                    "building_model_id": model_id,
                    "building_id": building_id,
                    "device_type": "hvac_heating",
                    "rated_power_kw": 6.0,
                    "controllable": True,
                    "flexibility_role": "soft_cls_provider",
                    "source_standard": "pycity-inspired",
                    "ev_id": None,
                },
                {
                    "device_id": f"device:{building_id}:hvac_cooling",
                    "building_model_id": model_id,
                    "building_id": building_id,
                    "device_type": "hvac_cooling",
                    "rated_power_kw": 3.0,
                    "controllable": True,
                    "flexibility_role": "soft_cls_provider",
                    "source_standard": "pycity-inspired",
                    "ev_id": None,
                },
            ]
        )
    return pd.DataFrame(rows)


def _asset_registry() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "scenario_id": "S1",
                "building_id": "building:1",
                "soft_cls_participant": True,
                "hard_cls_enabled": False,
                "has_ev": False,
                "ev_id": None,
                "charger_kw": 0.0,
                "contract_type": "soft_building",
                "max_soft_kw": 5.0,
                "max_hard_kw": 0.0,
            },
            {
                "scenario_id": "S1",
                "building_id": "building:2",
                "soft_cls_participant": True,
                "hard_cls_enabled": True,
                "has_ev": True,
                "ev_id": "ev:S1:2",
                "charger_kw": 7.2,
                "contract_type": "soft+hard_ev",
                "max_soft_kw": 4.0,
                "max_hard_kw": 7.2,
            },
            {
                "scenario_id": "S1",
                "building_id": "building:3",
                "soft_cls_participant": False,
                "hard_cls_enabled": False,
                "has_ev": False,
                "ev_id": None,
                "charger_kw": 0.0,
                "contract_type": "none",
                "max_soft_kw": 0.0,
                "max_hard_kw": 0.0,
            },
        ]
    )


class BuildingScenarioModelsTest(unittest.TestCase):
    def test_scenario_overlay_selects_only_participating_devices(self):
        tables = synthesize_scenario_device_tables(
            _building_models(),
            _base_devices(),
            _asset_registry(),
            scenario_id="S1",
        )
        devices = tables["scenario_device_registry"]

        self.assertEqual(set(devices["scenario_id"]), {"S1"})
        self.assertEqual(len(devices), 5)
        self.assertEqual((devices["contract_role"] == "soft_cls_provider").sum(), 4)
        self.assertEqual((devices["contract_role"] == "hard_cls_backstop").sum(), 1)
        self.assertNotIn("building:3", set(devices["building_id"]))

        evse = devices[devices["device_type"] == "evse_l2"].iloc[0]
        self.assertEqual(evse["ev_id"], "ev:S1:2")
        self.assertEqual(evse["available_kw"], 7.2)
        self.assertEqual(evse["constraint_zone_id"], "transformer:8")
        self.assertEqual(evse["aggregator_id"], "aggregator:S1:default")

    def test_write_scenario_model_artifacts_writes_manifest_and_summary(self):
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            out_dir = root / "digital_twin" / "models" / "scenarios"
            manifest = write_scenario_model_artifacts(
                _building_models(),
                _base_devices(),
                _asset_registry(),
                out_dir=out_dir,
                root=root,
            )

            manifest_path = out_dir / "scenario_model_manifest.json"
            self.assertTrue(manifest_path.exists())
            persisted_manifest = json.loads(manifest_path.read_text())
            self.assertEqual(manifest, persisted_manifest)
            self.assertEqual(manifest["counts"]["scenarios"], 1)
            self.assertEqual(manifest["scenario_counts"]["S1"]["scenario_devices"], 5)
            self.assertEqual(manifest["scenario_counts"]["S1"]["ev_buildings"], 1)
            self.assertEqual(manifest["scenario_counts"]["S1"]["soft_cls_buildings"], 2)
            self.assertEqual(manifest["scenario_counts"]["S1"]["hard_cls_evs"], 1)
            self.assertEqual(manifest["scenario_counts"]["S1"]["hard_only_evs"], 0)
            self.assertEqual(manifest["scenario_counts"]["S1"]["soft_hard_overlap"], 1)
            self.assertEqual(manifest["scenario_counts"]["S1"]["evse_devices"], 1)
            self.assertEqual(
                manifest["artifacts"]["S1_device_registry"],
                "digital_twin/models/scenarios/S1_device_registry.parquet",
            )
            self.assertTrue((out_dir / "S1_device_registry.parquet").exists())
            self.assertTrue((out_dir / "scenario_summary.parquet").exists())


if __name__ == "__main__":
    unittest.main()
