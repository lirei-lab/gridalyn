import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from gridalyn.twin import NetworkModelRepository
from gridalyn.twin.network import (
    PROVENANCE_ABSENT,
    PROVENANCE_DECLARED,
    MissingProvenanceWarning,
    write_base_metadata,
)


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

    def test_load_without_metadata_is_marked_degraded_never_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._write_base_model(base)

            repo = NetworkModelRepository.from_parquet(base)
            with self.assertWarns(MissingProvenanceWarning) as caught:
                model = repo.load_model()

        self.assertEqual(model.provenance_status, PROVENANCE_ABSENT)
        self.assertFalse(model.has_provenance)
        self.assertIsNone(model.identity)
        self.assertIn("metadata.json", str(caught.warning))
        self.assertIn("write_base_metadata", str(caught.warning))

    def test_load_without_metadata_raises_when_provenance_is_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._write_base_model(base)

            repo = NetworkModelRepository.from_parquet(base, provenance="require")
            with self.assertRaises(FileNotFoundError) as caught:
                repo.load_model()

        self.assertIn("metadata.json", str(caught.exception))
        self.assertIn("write_base_metadata", str(caught.exception))

    def test_load_populates_cgmes_identity_from_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base"
            base.mkdir()
            self._write_base_model(base)
            write_base_metadata(
                base_dir=base,
                root=root,
                config_path=root / "config.json",
                config_hash="abc123",
                created_at="2026-08-12T00:00:00+00:00",
            )

            repo = NetworkModelRepository.from_parquet(base, provenance="require")
            model = repo.load_model()
            manifest = json.loads((base / "metadata.json").read_text())

        self.assertEqual(model.provenance_status, PROVENANCE_DECLARED)
        self.assertTrue(model.has_provenance)
        assert model.identity is not None
        self.assertEqual(model.identity.id, manifest["model_version_id"])
        self.assertEqual(model.identity.created, "2026-08-12T00:00:00+00:00")
        # Renamed in review cycle 1 of Phase 11: this holds the governance
        # contract version, a constant for every model this repo can produce,
        # not the CGMES `version` that orders revisions of one model.
        self.assertEqual(model.identity.governance_schema_version, "1.0")
        self.assertEqual(model.identity.profile, "gridalyn:digital-twin-base:1.0")
        # Renamed from `dependent_on`: these are parquet paths, not the model
        # mRIDs CGMES `Model.DependentOn` references.
        self.assertIn("base/grid_buses.parquet", model.identity.artifact_paths)
        self.assertEqual(model.source_adapter, "SyntheticPandapowerAdapter")
        # scenarioTime has no source in the base artifacts and is never faked.
        self.assertIsNone(model.identity.scenario_time)

    def test_load_rejects_a_corrupt_metadata_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._write_base_model(base)
            (base / "metadata.json").write_text("{not json")

            repo = NetworkModelRepository.from_parquet(base)
            with self.assertRaises(ValueError) as caught:
                repo.load_model()

        self.assertIn("metadata.json", str(caught.exception))
        self.assertIn("not valid JSON", str(caught.exception))

    def test_loads_parquet_model_and_queries_downstream_transformer(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._write_base_model(base)

            repo = NetworkModelRepository.from_parquet(base, provenance="ignore")
            model = repo.load_model()
            downstream = repo.get_downstream("transformer:0")

        self.assertEqual(downstream.upstream_id, "transformer:0")
        self.assertEqual(model.counts["buses"], 4)
        self.assertIn("building:0", downstream.building_ids)
        self.assertIn("building:1", downstream.building_ids)
        self.assertIn("load:0", downstream.load_ids)
        self.assertIn("bus:load_1", downstream.bus_ids)

    def test_queries_feeder_by_lv_feeder_bus(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._write_base_model(base)

            repo = NetworkModelRepository.from_parquet(base, provenance="ignore")
            feeder = repo.get_feeder("bus:lv_0")

        # Renamed from `constraint_id` in Phase 11 (plan 11-03): this query
        # takes a feeder, and the field never held a constraint.
        self.assertEqual(feeder.upstream_id, "bus:lv_0")
        self.assertEqual(feeder.building_ids, ("building:0", "building:1"))
        self.assertEqual(feeder.load_ids, ("load:0", "load:1"))
        self.assertEqual(feeder.bus_ids, ("bus:load_0", "bus:load_1"))

    def test_queries_equipment_connected_to_bus(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._write_base_model(base)

            repo = NetworkModelRepository.from_parquet(base, provenance="ignore")
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
                [
                    {
                        "line_id": "line:bad",
                        "from_bus_id": "bus:load_0",
                        "to_bus_id": "bus:missing",
                    }
                ]
            ).to_parquet(base / "grid_lines.parquet")

            repo = NetworkModelRepository.from_parquet(base, provenance="ignore")
            report = repo.validate_integrity()

        self.assertFalse(report.valid)
        self.assertIn(
            "line line:bad references missing to_bus_id bus:missing", report.errors
        )


if __name__ == "__main__":
    unittest.main()
