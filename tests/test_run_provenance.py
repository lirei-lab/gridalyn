"""Provenance-block contract for the project run manifest (REPRO-04).

The run manifest must additively record an interpreter/clearing-engine/seed/
input-hash provenance block without breaking the frozen report contract
(``REQUIRED_REPORT_FIELDS`` / ``validate_report``). The clearing-engine name is
asserted against the SINGLE canonical ``runner.CLEARING_ENGINE_NAME`` constant
(imported here, never re-stated as a literal) so the write site and the test can
never silently diverge.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from gridalyn.foundation.platform.reports import REQUIRED_REPORT_FIELDS, validate_report
from gridalyn.projects import init_project, run_workflow
from gridalyn.projects.runner import CLEARING_ENGINE_NAME
from gridalyn.simulation.backends.contract import (
    DEFAULT_POWERFLOW_BACKEND_ID,
    LIGHTSIM2GRID_BACKEND_ID,
    PANDAPOWER_NATIVE_BACKEND_ID,
)


def _grid_study_project(tmp: str) -> Path:
    target = Path(tmp) / "my_case"
    init_project(target, name="my_case", template="grid-study")
    return target


def _run_manifest(tmp: str) -> dict:
    target = _grid_study_project(tmp)
    run_workflow(target, dry_run=True)
    manifest_path = target / "outputs" / "manifests" / "project_run_manifest.json"
    return json.loads(manifest_path.read_text(encoding="utf-8"))


class TestRunProvenance(unittest.TestCase):
    def test_manifest_carries_top_level_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = _run_manifest(tmp)
            self.assertIn("provenance", manifest)
            self.assertIsInstance(manifest["provenance"], dict)

    def test_python_version_is_non_empty_dotted_string(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provenance = _run_manifest(tmp)["provenance"]
            version = provenance["python_version"]
            self.assertIsInstance(version, str)
            self.assertTrue(version)
            self.assertIn(".", version)

    def test_pythonhashseed_matches_runtime_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provenance = _run_manifest(tmp)["provenance"]
            self.assertEqual(
                provenance["pythonhashseed"],
                os.environ.get("PYTHONHASHSEED"),
            )

    def test_clearing_engine_name_is_single_canonical_constant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provenance = _run_manifest(tmp)["provenance"]
            engine = provenance["clearing_engine"]
            self.assertEqual(engine["name"], CLEARING_ENGINE_NAME)
            # The constant must be a real clearing mode, never a drifted literal.
            self.assertIn(CLEARING_ENGINE_NAME, {"engine_mode", "selection"})

    def test_clearing_engine_version_is_numeric_stack_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provenance = _run_manifest(tmp)["provenance"]
            version = provenance["clearing_engine"]["version"]
            self.assertIsInstance(version, dict)
            self.assertIn("numpy", version)

    def test_seeds_block_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provenance = _run_manifest(tmp)["provenance"]
            self.assertIn("seeds", provenance)
            self.assertIsInstance(provenance["seeds"], dict)

    def test_seeds_block_states_whether_a_base_was_declared(self) -> None:
        # The seeds block used to be a per-stage {stage_id: seed + index} map.
        # No study seeds that way, so the map asserted a derivation the stages
        # do not perform. It now records the declared base and says whether it
        # was declared -- absent provenance being strictly better than false
        # provenance.
        with tempfile.TemporaryDirectory() as tmp:
            seeds = _run_manifest(tmp)["provenance"]["seeds"]
            self.assertIn("base", seeds)
            self.assertIn("declared", seeds)
            self.assertIsInstance(seeds["declared"], bool)
            self.assertIsInstance(seeds["stage_count"], int)
            if seeds["declared"]:
                self.assertIsInstance(seeds["base"], int)
            else:
                self.assertIsNone(seeds["base"])


class TestShippedStudiesDeclareSeeds(unittest.TestCase):
    """Every shipped study must declare the RNG base it actually uses.

    This pins a repaired defect rather than a preference. ``_resolve_seeds``
    documented ``spec.simulation.seed`` as its primary path, but the study
    schema set ``spec.additionalProperties: false`` without listing
    ``simulation``, so declaring the key failed validation and every study fell
    to the fallback. All eight manifests on disk recorded
    ``{"base": null}`` -- a reproducibility repository whose governed artifacts
    recorded no seed at all. Without this test, deleting one line of schema
    silently restores that state.
    """

    def test_every_study_declares_a_seed_the_runner_can_record(self) -> None:
        from gridalyn.projects.loader import load_project
        from gridalyn.projects.runner import _resolve_seeds, plan_stages

        repo_root = Path(__file__).resolve().parents[1]
        project_files = sorted((repo_root / "projects").glob("*/project.yaml"))
        self.assertTrue(project_files, "no shipped studies found")
        undeclared = []
        for path in project_files:
            project = load_project(path)
            seeds = _resolve_seeds(project, plan_stages(project))
            if not seeds["declared"] or not isinstance(seeds["base"], int):
                undeclared.append(path.parent.name)
        self.assertEqual(
            undeclared,
            [],
            "these studies record no RNG base in provenance; add "
            "spec.simulation.seed naming the base the stage scripts actually "
            f"use: {', '.join(undeclared)}",
        )

    def test_declared_seed_survives_schema_validation(self) -> None:
        from gridalyn.projects.validation import validate_project_file

        repo_root = Path(__file__).resolve().parents[1]
        for path in sorted((repo_root / "projects").glob("*/project.yaml")):
            with self.subTest(study=path.parent.name):
                report = validate_project_file(path)
                self.assertTrue(report.valid, report.errors)

    def test_powerflow_backend_block_present(self) -> None:
        # Phase 10, plan 10-01. Before this key existed, a run solved through
        # lightsim2grid and a run solved through pandapower's own
        # Newton-Raphson were indistinguishable in every governed artifact.
        with tempfile.TemporaryDirectory() as tmp:
            provenance = _run_manifest(tmp)["provenance"]
            self.assertIn("powerflow_backend", provenance)
            self.assertIsInstance(provenance["powerflow_backend"], dict)

    def test_powerflow_backend_records_engine_id_and_settings(self) -> None:
        # "Engine AND settings" is the point: an engine id alone would not say
        # what was asked of the solver.
        with tempfile.TemporaryDirectory() as tmp:
            backend = _run_manifest(tmp)["provenance"]["powerflow_backend"]
            self.assertEqual(DEFAULT_POWERFLOW_BACKEND_ID, backend["backend_id"])
            self.assertEqual(PANDAPOWER_NATIVE_BACKEND_ID, backend["backend_id"])
            self.assertIsInstance(backend["settings"], dict)
            self.assertEqual({"algorithm": "nr", "init": "auto"}, backend["settings"])
            self.assertIsInstance(backend["name"], str)
            self.assertTrue(backend["name"])
            # The default must need no optional extra, or the manifest would
            # record a backend the environment cannot serve.
            self.assertIsNone(backend["capability"])

    def test_powerflow_backend_lists_registered_ids_and_availability(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            backend = _run_manifest(tmp)["provenance"]["powerflow_backend"]
            self.assertEqual(
                sorted([LIGHTSIM2GRID_BACKEND_ID, PANDAPOWER_NATIVE_BACKEND_ID]),
                sorted(backend["registered"]),
            )
            self.assertEqual(
                sorted(backend["registered"]), sorted(backend["available"])
            )
            for backend_id, is_available in backend["available"].items():
                self.assertIsInstance(is_available, bool, backend_id)
            # The default backend needs no extra, so it is always available.
            self.assertTrue(backend["available"][DEFAULT_POWERFLOW_BACKEND_ID])

    def test_powerflow_backend_block_is_json_native(self) -> None:
        # It is embedded in the manifest with the stdlib encoder; a
        # MappingProxyType or a class would break the write, not the read.
        with tempfile.TemporaryDirectory() as tmp:
            backend = _run_manifest(tmp)["provenance"]["powerflow_backend"]
            self.assertEqual(backend, json.loads(json.dumps(backend)))

    def test_input_hashes_block_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            provenance = _run_manifest(tmp)["provenance"]
            self.assertIn("input_hashes", provenance)
            self.assertIsInstance(provenance["input_hashes"], dict)

    def test_input_hashes_carry_sha256_for_existing_files(self) -> None:
        # A governed study commits a TMY CSV and a regression baseline;
        # when the runner can see them it records a sha256 per file_reference.
        with tempfile.TemporaryDirectory() as tmp:
            target = _grid_study_project(tmp)
            inputs_dir = target / "inputs"
            inputs_dir.mkdir(parents=True, exist_ok=True)
            (inputs_dir / "tmy_trois_rivieres.csv").write_text(
                "timestamp,ghi\n2020-01-01T00:00:00Z,0\n", encoding="utf-8"
            )
            baselines_dir = target / "baselines"
            baselines_dir.mkdir(parents=True, exist_ok=True)
            (baselines_dir / "results_baseline.json").write_text(
                json.dumps({"metrics": []}), encoding="utf-8"
            )
            run_workflow(target, dry_run=True)
            manifest_path = (
                target / "outputs" / "manifests" / "project_run_manifest.json"
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            input_hashes = manifest["provenance"]["input_hashes"]
            self.assertTrue(input_hashes, "expected pinned-input hash records")
            for record in input_hashes.values():
                self.assertIn("sha256", record)

    def test_provenance_is_contract_safe(self) -> None:
        # validate_report only flags MISSING required fields and never rejects
        # extra keys, so the additive provenance block cannot break the contract.
        with tempfile.TemporaryDirectory() as tmp:
            manifest = _run_manifest(tmp)
            payload = {name: "x" for name in REQUIRED_REPORT_FIELDS}
            payload["schema_version"] = "1.0"
            payload["inputs"] = []
            payload["artifacts"] = []
            payload["summary"] = {}
            payload["validation"] = {}
            payload["provenance"] = manifest["provenance"]
            errors = validate_report(payload)
            self.assertEqual([e for e in errors if "missing required field" in e], [])

    def test_required_report_fields_unchanged(self) -> None:
        self.assertEqual(
            REQUIRED_REPORT_FIELDS,
            (
                "report_id",
                "schema_version",
                "created_at",
                "source_domain",
                "inputs",
                "artifacts",
                "summary",
                "validation",
            ),
        )


if __name__ == "__main__":
    unittest.main()
