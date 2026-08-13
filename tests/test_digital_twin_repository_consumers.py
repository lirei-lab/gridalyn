import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from gridalyn.projects.workflows.scripts.generate_digital_twin_flexibility_providers import (
    generate_flexibility_provider_artifacts,
)
from gridalyn.projects.workflows.scripts.generate_digital_twin_semantic_graph import (
    generate_semantic_graph,
)


class DigitalTwinRepositoryConsumersTest(unittest.TestCase):
    def _base_model(self):
        class FakeIdentity:
            id = "model:sha256:fake-identity"

        class FakeModel:
            counts = {
                "buses": 1,
                "lines": 1,
                "transformers": 1,
                "buildings": 1,
                "loads": 1,
                "connectivity": 1,
            }
            identity = FakeIdentity()
            buses = pd.DataFrame(
                [
                    {
                        "bus_id": "bus:0",
                        "pandapower_bus": 0,
                        "name": "lv_bus_0",
                        "voltage_kv": 0.4,
                        "category": "LV",
                    }
                ]
            )
            lines = pd.DataFrame(
                [{"line_id": "line:0", "from_bus_id": "bus:0", "to_bus_id": "bus:0"}]
            )
            transformers = pd.DataFrame(
                [
                    {
                        "transformer_id": "transformer:0",
                        "hv_bus_id": "bus:0",
                        "lv_bus_id": "bus:0",
                    }
                ]
            )
            buildings = pd.DataFrame(
                [
                    {
                        "building_id": "building:0",
                        "load_id": "load:0",
                        "pandapower_load": 0,
                        "lv_bus_id": "bus:0",
                        "static_p_mw": 0.01,
                    }
                ]
            )
            connectivity = pd.DataFrame(
                [
                    {
                        "building_id": "building:0",
                        "load_id": "load:0",
                        "load_bus_id": "bus:0",
                        "lv_feeder_bus_id": "bus:0",
                        "lv_transformer_id": "transformer:0",
                    }
                ]
            )

        return FakeModel()

    def _repository_class(self):
        model = self._base_model()

        class FakeReport:
            valid = True
            errors = ()
            warnings = ()

        class FakeRepository:
            @classmethod
            def from_parquet(cls, base_dir):
                self = cls()
                self.base_dir = base_dir
                return self

            def load_model(self):
                return model

            def validate_integrity(self):
                return FakeReport()

        return FakeRepository

    def _read_parquet_side_effect(self, path, *args, **kwargs):
        path = Path(path)
        if path.name in {
            "grid_buses.parquet",
            "grid_lines.parquet",
            "grid_transformers.parquet",
            "buildings.parquet",
            "building_grid_connectivity.parquet",
        }:
            raise AssertionError(f"raw base parquet read: {path.name}")
        if path.name == "asset_registry.parquet":
            return pd.DataFrame(
                [
                    {
                        "scenario_id": "S4",
                        "building_id": "building:0",
                        "load_id": "load:0",
                        "pandapower_load": 0,
                        "has_ev": True,
                        "ev_id": "ev:S4:0",
                        "charger_kw": 7.2,
                        "soft_cls_participant": True,
                        "hard_cls_enabled": True,
                        "max_soft_kw": 5.0,
                        "max_hard_kw": 7.2,
                    }
                ]
            )
        if path.name == "provider_registry.parquet":
            return pd.DataFrame()
        if path.name.endswith("_device_registry.parquet"):
            return pd.DataFrame()
        raise AssertionError(f"unexpected parquet read: {path}")

    def test_semantic_graph_generation_uses_network_repository_for_base_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scenario_dir = root / "scenarios"
            flexibility_dir = root / "flexibility"
            timeseries_dir = root / "timeseries"
            out_dir = root / "semantic"
            for path in [scenario_dir, flexibility_dir, timeseries_dir]:
                path.mkdir(parents=True)
            (timeseries_dir / "powerflow_smoke_summary.json").write_text(json.dumps({}))
            (timeseries_dir / "ev_load_summary.json").write_text(json.dumps({}))

            with (
                patch(
                    "gridalyn.projects.workflows.scripts.generate_digital_twin_semantic_graph.NetworkModelRepository",
                    self._repository_class(),
                    create=True,
                ),
                patch.object(
                    pd, "read_parquet", side_effect=self._read_parquet_side_effect
                ),
            ):
                nodes, edges, manifest = generate_semantic_graph(
                    profile="north_america",
                    base_dir=root / "base",
                    scenario_dir=scenario_dir,
                    flexibility_dir=flexibility_dir,
                    timeseries_dir=timeseries_dir,
                    out_dir=out_dir,
                )

        self.assertEqual(manifest["semantic_profile"], "north_america")
        self.assertIn("building:0", set(nodes["node_id"]))
        self.assertGreaterEqual(len(edges), 1)

    def test_flexibility_provider_generation_uses_network_repository_for_connectivity(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scenario_dir = root / "scenarios"
            models_dir = root / "models"
            out_dir = root / "flexibility"
            scenario_model_dir = models_dir / "scenarios"
            scenario_dir.mkdir(parents=True)
            scenario_model_dir.mkdir(parents=True)

            with (
                patch(
                    "gridalyn.projects.workflows.scripts.generate_digital_twin_flexibility_providers.NetworkModelRepository",
                    self._repository_class(),
                    create=True,
                ),
                patch.object(
                    pd, "read_parquet", side_effect=self._read_parquet_side_effect
                ),
            ):
                summary = generate_flexibility_provider_artifacts(
                    base_dir=root / "base",
                    scenario_dir=scenario_dir,
                    models_dir=models_dir,
                    out_dir=out_dir,
                )

            self.assertEqual(summary["n_providers"], 2)
            self.assertTrue((out_dir / "provider_registry.parquet").exists())

    def test_dashboard_catalog_model_version_id_comes_from_model_identity(self):
        # The catalog's model_version_id must be sourced from the identity
        # layer (model.identity.id), not read back out of the raw metadata
        # dict: the fake repository points at a base with no metadata.json, so
        # the raw read would yield None while the identity carries the id.
        from gridalyn.projects.dashboard_catalog import build_dashboard_catalog

        repository = self._repository_class().from_parquet(Path("nonexistent_base_dir"))
        catalog = build_dashboard_catalog(
            scenario_index={},
            powerflow_summary={},
            optional_extensions=None,
            root=Path("."),
            network_repository=repository,
        )

        self.assertEqual(
            catalog["network_model"]["model_version_id"],
            repository.load_model().identity.id,
        )
        self.assertEqual(
            catalog["network_model"]["model_version_id"],
            "model:sha256:fake-identity",
        )


if __name__ == "__main__":
    unittest.main()
