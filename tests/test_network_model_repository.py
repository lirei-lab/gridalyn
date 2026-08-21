import json
import tempfile
import unittest
import warnings
from pathlib import Path

import pandas as pd

from gridalyn.twin import NetworkModelRepository
from gridalyn.twin.network import (
    DEFAULT_OPERATIONAL_STATE,
    OPERATIONAL_STATES,
    PROVENANCE_ABSENT,
    PROVENANCE_DECLARED,
    MissingProvenanceWarning,
    NetworkModel,
    write_base_metadata,
)

# Distinguishes "remove the key" from "set it to null": both are
# meaningful manifest states and they resolve differently.
_ABSENT = object()


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
        # No manifest AND no declared state -- the shape of every existing
        # base_dir-only caller. Degraded provenance must still resolve a state,
        # not leave it None.
        self.assertEqual(model.operational_state, DEFAULT_OPERATIONAL_STATE)
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

    def _write_base_model_with_manifest(self, root: Path) -> Path:
        """Write a base plus its manifest, so loading emits no provenance warning."""
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
        return base

    def test_load_defaults_operational_state_to_base_when_undeclared(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._write_base_model_with_manifest(Path(tmp))

            repo = NetworkModelRepository(base_dir=base)
            model = repo.load_model()
            manifest = json.loads((base / "metadata.json").read_text())
            resolved = repo.resolved_operational_state()

        # The manifest a state-blind producer writes carries no key at all, so
        # this really is the default leg and not the manifest leg wearing its
        # name.
        self.assertNotIn("operational_state", manifest)
        # An existing base_dir-only caller changes nothing and still gets a
        # state: undeclared on the repository, resolved to "base" on the model.
        self.assertIsNone(repo.operational_state)
        self.assertEqual(resolved, DEFAULT_OPERATIONAL_STATE)
        self.assertEqual(model.operational_state, "base")

    def test_load_stamps_the_declared_operational_state_on_both_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with_manifest = self._write_base_model_with_manifest(root)
            without_manifest = root / "bare"
            without_manifest.mkdir()
            self._write_base_model(without_manifest)

            declared = NetworkModelRepository.from_parquet(
                with_manifest, operational_state="planned"
            )
            bare = NetworkModelRepository.from_parquet(
                without_manifest, provenance="ignore", operational_state="planned"
            )
            declared_model = declared.load_model()
            bare_model = bare.load_model()

        self.assertEqual(declared_model.provenance_status, PROVENANCE_DECLARED)
        self.assertEqual(declared_model.operational_state, "planned")
        # The manifest-absent early return is the branch a manifest-only test
        # would miss: it must carry the declared state, not fall back to None.
        self.assertEqual(bare_model.provenance_status, PROVENANCE_ABSENT)
        self.assertEqual(bare_model.operational_state, "planned")

    def test_unknown_operational_state_is_rejected_with_the_valid_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            # Case variants are rejected, never silently lowercased: coercing
            # "Base" would hide the caller's typo.
            for unknown in ("Base", "STUDY_CASE", "", "bogus"):
                with self.subTest(unknown=unknown):
                    with self.assertRaises(ValueError) as caught:
                        NetworkModelRepository(base_dir=base, operational_state=unknown)
                    message = str(caught.exception)
                    self.assertIn(repr(unknown), message)
                    self.assertIn(str(base), message)
                    # As one unit: asserting each state separately is vacuous
                    # for "base", which the message already contains via
                    # base_dir=..., so a dropped entry would go unnoticed.
                    self.assertIn(", ".join(OPERATIONAL_STATES), message)

    def test_declared_base_stays_distinguishable_from_undeclared(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._write_base_model_with_manifest(Path(tmp))

            undeclared = NetworkModelRepository(base_dir=base)
            explicit = NetworkModelRepository(base_dir=base, operational_state="base")
            undeclared_model = undeclared.load_model()
            explicit_model = explicit.load_model()

        # The sentinel must survive refactoring: "the caller said nothing" and
        # "the caller asked for base" resolve alike but are not the same value.
        self.assertIsNone(undeclared.operational_state)
        self.assertEqual(explicit.operational_state, "base")
        self.assertEqual(undeclared_model.operational_state, "base")
        self.assertEqual(explicit_model.operational_state, "base")

    def _manifest_with_state(self, root: Path, state: str) -> Path:
        """Write a base whose manifest records ``state``, and return the base."""
        base = root / "base"
        base.mkdir()
        self._write_base_model(base)
        write_base_metadata(
            base_dir=base,
            root=root,
            config_path=root / "config.json",
            config_hash="abc123",
            operational_state=state,
            created_at="2026-08-12T00:00:00+00:00",
        )
        return base

    def _rewrite_manifest_state(self, base: Path, value: object) -> None:
        """Replace the manifest's operational state, or drop the key entirely."""
        path = base / "metadata.json"
        manifest = json.loads(path.read_text())
        if value is _ABSENT:
            manifest.pop("operational_state", None)
        else:
            manifest["operational_state"] = value
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True))

    def test_operational_state_round_trips_through_the_metadata_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._manifest_with_state(Path(tmp), "planned")

            repo = NetworkModelRepository.from_parquet(base, provenance="require")
            model = repo.load_model()
            manifest = json.loads((base / "metadata.json").read_text())

        # The writer records it and the reader reads it back: an undeclared
        # repository adopts the state the snapshot itself claims.
        self.assertEqual(manifest["operational_state"], "planned")
        self.assertIsNone(repo.operational_state)
        self.assertEqual(model.operational_state, "planned")

    def test_declared_state_overrides_the_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._manifest_with_state(Path(tmp), "planned")

            repo = NetworkModelRepository.from_parquet(
                base, provenance="require", operational_state="current"
            )
            model = repo.load_model()

        # The decisive leg of the precedence rule: an explicit caller wins over
        # what the manifest on disk says.
        self.assertEqual(model.operational_state, "current")

    def test_manifest_without_operational_state_still_loads_as_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._manifest_with_state(Path(tmp), "planned")
            self._rewrite_manifest_state(base, _ABSENT)

            repo = NetworkModelRepository.from_parquet(base, provenance="require")
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                model = repo.load_model()

        # The committed instances/default/.../base/metadata.json predates this
        # key; it must keep loading, silently, as the base snapshot it is.
        self.assertEqual(model.operational_state, DEFAULT_OPERATIONAL_STATE)
        self.assertEqual([str(w.message) for w in caught], [])

    def test_manifest_with_unknown_operational_state_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._manifest_with_state(Path(tmp), "planned")
            repo = NetworkModelRepository.from_parquet(base, provenance="require")
            manifest_path = str(base / "metadata.json")

            self._rewrite_manifest_state(base, "bogus")
            with self.assertRaises(ValueError) as unknown:
                repo.load_model()

            # A non-string is named by type, never coerced. An explicit JSON
            # null is a third, distinct case: it must not degrade to the
            # default just because `None` is the undeclared sentinel elsewhere.
            self._rewrite_manifest_state(base, 42)
            with self.assertRaises(ValueError) as wrong_type:
                repo.load_model()

            self._rewrite_manifest_state(base, None)
            with self.assertRaises(ValueError) as null_state:
                repo.load_model()

        message = str(unknown.exception)
        self.assertIn(manifest_path, message)
        self.assertIn("'bogus'", message)
        self.assertIn(", ".join(OPERATIONAL_STATES), message)
        self.assertIn("write_base_metadata", message)

        type_message = str(wrong_type.exception)
        self.assertIn(manifest_path, type_message)
        self.assertIn("int", type_message)
        # The valid set belongs in the non-string message too: a caller told
        # only "must be a string" still has to guess which strings.
        self.assertIn(", ".join(OPERATIONAL_STATES), type_message)

        null_message = str(null_state.exception)
        self.assertIn(manifest_path, null_message)
        self.assertIn("NoneType", null_message)

    def test_corrupt_manifest_is_rejected_whether_or_not_a_state_is_declared(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._manifest_with_state(Path(tmp), "planned")
            self._rewrite_manifest_state(base, 42)

            silent = NetworkModelRepository.from_parquet(base, provenance="require")
            declaring = NetworkModelRepository.from_parquet(
                base, provenance="require", operational_state="current"
            )

            # Precedence decides which VALID value wins; it must never decide
            # whether the file on disk is checked at all. Before this, an
            # unrelated constructor argument silently disabled the check.
            with self.assertRaises(ValueError):
                silent.load_model()
            with self.assertRaises(ValueError):
                declaring.load_model()

    def test_the_remedy_named_by_a_manifest_error_preserves_the_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = self._manifest_with_state(root, "planned")
            self._rewrite_manifest_state(base, "bogus")
            repo = NetworkModelRepository.from_parquet(base, provenance="require")

            with self.assertRaises(ValueError) as caught:
                repo.load_model()
            message = str(caught.exception)

            # The remedy is *performed*, not quoted: an earlier version of this
            # test asserted three substrings and so certified advice that
            # raised the very error it claimed to fix. Clause one -- rewrite
            # through the writer -- must succeed against the corrupt manifest
            # it replaces, and must keep the state a declared state.
            write_base_metadata(
                base_dir=base,
                root=root,
                config_path=root / "config.json",
                config_hash="abc123",
                operational_state="planned",
                created_at="2026-08-12T00:00:00+00:00",
            )
            rewritten = repo.load_model().operational_state

            # Clause two -- correct the key by hand -- is the fallback for a
            # reader who cannot reach the writer, so it is exercised from the
            # same poisoned starting point.
            self._rewrite_manifest_state(base, "bogus")
            with self.assertRaises(ValueError):
                repo.load_model()
            self._rewrite_manifest_state(base, "current")
            by_hand = repo.load_model().operational_state

        self.assertEqual(rewritten, "planned")
        self.assertEqual(by_hand, "current")
        # Secondary check only: the message must still name the two remedies
        # this test just executed, so advice and behaviour cannot drift apart.
        self.assertIn(
            "write_base_metadata(base_dir=..., root=..., operational_state=...)",
            message,
        )
        self.assertIn("metadata.json", message)
        self.assertIn("by hand", message)

    def test_the_writer_repairs_a_manifest_whose_operational_state_is_corrupt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = self._manifest_with_state(root, "planned")
            self._rewrite_manifest_state(base, "bogus")

            # The writer loads the model to count and validate it, so it reads
            # the manifest it is about to replace. Under provenance="ignore"
            # that manifest is not authority, so its state is not validated --
            # otherwise the one function able to repair a poisoned manifest
            # would be gated on the poison.
            path = write_base_metadata(
                base_dir=base,
                root=root,
                config_path=root / "config.json",
                config_hash="abc123",
                operational_state="current",
                created_at="2026-08-12T00:00:00+00:00",
            )
            manifest = json.loads(path.read_text())
            reloaded = NetworkModelRepository.from_parquet(
                base, provenance="require"
            ).load_model()

        self.assertEqual(manifest["operational_state"], "current")
        self.assertEqual(reloaded.operational_state, "current")

    def test_resolved_state_agrees_with_the_loaded_model_on_every_leg(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = self._manifest_with_state(Path(tmp), "planned")
            self._rewrite_manifest_state(base, _ABSENT)
            no_manifest_key = NetworkModelRepository.from_parquet(base)
            undeclared_pairs = [
                (
                    no_manifest_key.resolved_operational_state(),
                    no_manifest_key.load_model().operational_state,
                    DEFAULT_OPERATIONAL_STATE,
                )
            ]

            self._rewrite_manifest_state(base, "planned")
            from_manifest = NetworkModelRepository.from_parquet(base)
            declared = NetworkModelRepository.from_parquet(
                base, operational_state="current"
            )
            pairs = undeclared_pairs + [
                (
                    from_manifest.resolved_operational_state(),
                    from_manifest.load_model().operational_state,
                    "planned",
                ),
                (
                    declared.resolved_operational_state(),
                    declared.load_model().operational_state,
                    "current",
                ),
            ]

        # The accessor and the loader share one resolver, so they cannot
        # disagree -- on the declared leg, the manifest leg, or the default.
        for reported, stamped, expected in pairs:
            with self.subTest(expected=expected):
                self.assertEqual(reported, stamped)
                self.assertEqual(reported, expected)

    def test_resolved_state_obeys_the_provenance_policy_it_now_reads_under(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._write_base_model(base)

            # Reading the manifest is what makes the accessor agree with
            # load_model(), so it inherits load_model()'s provenance policy.
            with self.assertRaises(FileNotFoundError):
                NetworkModelRepository.from_parquet(
                    base, provenance="require"
                ).resolved_operational_state()

            with self.assertWarns(MissingProvenanceWarning):
                warned = NetworkModelRepository.from_parquet(
                    base
                ).resolved_operational_state()

            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                silent = NetworkModelRepository.from_parquet(
                    base, provenance="ignore", operational_state="study_case"
                ).resolved_operational_state()

        self.assertEqual(warned, DEFAULT_OPERATIONAL_STATE)
        self.assertEqual(silent, "study_case")
        self.assertEqual([str(w.message) for w in caught], [])

    def test_writer_rejects_a_state_no_repository_could_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base"
            base.mkdir()
            self._write_base_model(base)

            with self.assertRaises(ValueError) as caught:
                write_base_metadata(
                    base_dir=base,
                    root=root,
                    config_path=root / "config.json",
                    config_hash="abc123",
                    operational_state="Base",
                    created_at="2026-08-12T00:00:00+00:00",
                )

            # The poison is caught at the writer, not later by a different
            # module: a rejected call leaves no manifest behind at all.
            wrote_anything = (base / "metadata.json").exists()

        message = str(caught.exception)
        self.assertIn("'Base'", message)
        self.assertIn(", ".join(OPERATIONAL_STATES), message)
        self.assertFalse(wrote_anything)

    def test_a_model_built_without_a_repository_declares_no_operational_state(self):
        model = NetworkModel(
            buses=pd.DataFrame(),
            lines=pd.DataFrame(),
            transformers=pd.DataFrame(),
            buildings=pd.DataFrame(),
            connectivity=pd.DataFrame(),
        )

        # A model with no repository behind it has no evidence for any state,
        # so it must not claim "base".
        self.assertIsNone(model.operational_state)


if __name__ == "__main__":
    unittest.main()
