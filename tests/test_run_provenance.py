"""Provenance-block contract for the project run manifest (REPRO-04).

The run manifest must additively record an interpreter/clearing-engine/seed/
input-hash provenance block without breaking the frozen report contract
(``REQUIRED_REPORT_FIELDS`` / ``validate_report``). The clearing-engine name is
recorded only when a study declares one, and the declarable set is derived from
the clearing modules the package actually ships.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gridalyn.foundation.platform.reports import REQUIRED_REPORT_FIELDS, validate_report
from gridalyn.projects import init_project, run_workflow
from gridalyn.projects.runner import _extensions_provenance
from gridalyn.simulation.backends.contract import (
    DEFAULT_POWERFLOW_BACKEND_ID,
    LIGHTSIM2GRID_BACKEND_ID,
    PANDAPOWER_NATIVE_BACKEND_ID,
)
from gridalyn.simulation.backends.registry import PowerFlowBackendRegistry


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

    def test_declarable_modes_are_derived_from_the_shipped_modules(self) -> None:
        # This used to assert a hardcoded CLEARING_ENGINE_NAME against a
        # hardcoded set, which would still have accepted "engine_mode" after
        # that module was retired on 2026-08-15. The set is now read from the
        # package, so a retired mode leaves it without anyone editing a literal.
        from gridalyn.projects.runner import _clearing_modes

        modes = _clearing_modes()
        self.assertIn("selection", modes)
        self.assertNotIn("engine_mode", modes)
        self.assertNotIn("allocation", modes)

    def test_clearing_engine_is_null_for_a_study_that_does_not_clear(self) -> None:
        # This assertion used to read `engine["name"] == CLEARING_ENGINE_NAME`,
        # because the runner wrote the constant unconditionally. Measured on
        # 2026-08-14: no study workflow stage executes engine_mode, and the one
        # study that clears reaches clearing.selection -- so all eight manifests
        # named an engine no run had used. A scaffolded project clears nothing
        # and must say so.
        with tempfile.TemporaryDirectory() as tmp:
            engine = _run_manifest(tmp)["provenance"]["clearing_engine"]
            self.assertIsNone(engine["name"])
            self.assertFalse(engine["declared"])

    def test_only_a_clearing_study_declares_an_engine(self) -> None:
        from gridalyn.projects.loader import load_project
        from gridalyn.projects.runner import _clearing_engine_provenance

        repo_root = Path(__file__).resolve().parents[1]
        declared = {}
        for path in sorted((repo_root / "projects").glob("*/project.yaml")):
            record = _clearing_engine_provenance(load_project(path))
            if record["declared"]:
                declared[path.parent.name] = record["name"]
        # ev_hosting_flex is the only shipped study that reaches a clearing
        # surface, and it reaches `selection`. If this changes, the study that
        # started clearing must declare it rather than inherit a literal.
        self.assertEqual(declared, {"ev_hosting_flex": "selection"})

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
            scalar = isinstance(seeds["base"], int)
            streams = isinstance(seeds["streams"], dict) and all(
                isinstance(value, int) for value in seeds["streams"].values()
            )
            if not seeds["declared"] or not (scalar or streams):
                undeclared.append(path.parent.name)
        self.assertEqual(
            undeclared,
            [],
            "these studies record no RNG seed in provenance; add "
            "spec.simulation.seed (one stream) or spec.simulation.seeds (several) "
            f"naming what the stage scripts actually draw from: {undeclared}",
        )

    def test_declared_streams_are_the_ones_the_scripts_read(self) -> None:
        # F1/F2 of the branch review: the first pass declared a scalar seed for
        # all eight studies from `spec.inputs.loadGeneration.seed`, and two of
        # them draw from a SECOND stream as well -- the Q-learning exploration
        # RNG and the building-footprint RNG. Both scalars were false
        # provenance: they read as reproducible while the artifact that matters
        # came from an undeclared literal. Those two studies now declare named
        # streams AND their scripts read them through
        # ProjectScript.simulation_seed, so declaration and draw cannot diverge.
        # This test pins the wiring, which is the part a reader depends on.
        from gridalyn.projects.model_inputs import load_simulation_seed

        repo_root = Path(__file__).resolve().parents[1]
        wired = {
            "rl_voltage_control_lightsim": (
                ("loadGeneration", "policy"),
                "scripts/train_rl_agent.py",
            ),
            "synthetic_geojson_feeder": (
                ("loadGeneration", "footprints"),
                "scripts/generate_building_footprints.py",
            ),
        }
        for study, (streams, consumer) in wired.items():
            project_file = repo_root / "projects" / study / "project.yaml"
            source = (repo_root / "projects" / study / consumer).read_text()
            for stream in streams:
                with self.subTest(study=study, stream=stream):
                    self.assertIsInstance(
                        load_simulation_seed(project_file, stream), int
                    )
            # The non-loadGeneration stream must be read by the script, not
            # merely declared beside it.
            self.assertIn(
                'simulation_seed("' + streams[1] + '")',
                source,
                f"{study}/{consumer} declares the {streams[1]!r} stream but "
                "does not read it; a declared seed the code ignores is worse "
                "than no declaration",
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


# A child-process probe that registers a host extension into the generic
# engine's DEFAULT_REGISTRY and snapshots it, so the end-to-end "host
# extension -> provenance.extensions" path is proven without mutating the
# process-global registry in the pytest process.
_EXTENSIONS_PROBE = """\
import json

from gridalyn.foundation.platform.extensions import (
    ExtensionDescriptor,
    register_extension,
)
from gridalyn.projects.runner import _extensions_provenance

register_extension(
    lambda: "probe-instance",
    descriptor=ExtensionDescriptor(
        extension_id="host-probe-ext",
        role="data_source",
        name="Probe extension",
        version="1.0.0",
        contract_version="1",
        source="host",
    ),
)
print(json.dumps(_extensions_provenance()))
"""


class TestExtensionsProvenance(unittest.TestCase):
    """provenance.extensions records which extensions participated (Phase 16)."""

    def test_manifest_extensions_block_present_and_is_a_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            extensions = _run_manifest(tmp)["provenance"]["extensions"]
        self.assertIsInstance(extensions, list)

    def test_manifest_extensions_block_is_json_native(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            extensions = _run_manifest(tmp)["provenance"]["extensions"]
        self.assertEqual(extensions, json.loads(json.dumps(extensions)))

    def test_extensions_provenance_empty_when_nothing_registered(self) -> None:
        # A clean registry yields an empty list, so shipped manifest bytes stay
        # identical (R7). The real DEFAULT_REGISTRY may carry residue from
        # other tests, so the source snapshot is patched to the clean state.
        with mock.patch(
            "gridalyn.foundation.platform.extensions.extension_provenance",
            return_value=[],
        ):
            self.assertEqual([], _extensions_provenance())

    def test_host_extension_appears_in_extensions_snapshot(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-c", _EXTENSIONS_PROBE],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[1],
            timeout=120,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr[-2000:])
        snapshot = json.loads(completed.stdout)
        ids = [row["extension_id"] for row in snapshot]
        self.assertIn("host-probe-ext", ids)
        row = next(
            record for record in snapshot if record["extension_id"] == "host-probe-ext"
        )
        self.assertEqual("host", row["source"])
        self.assertEqual("1", row["contract_version"])


def _grid_study_declaring_backend(tmp: str, backend_id: str) -> Path:
    """Scaffold a grid-study project that declares ``backend_id``."""
    import yaml

    target = _grid_study_project(tmp)
    project_file = target / "project.yaml"
    data = yaml.safe_load(project_file.read_text(encoding="utf-8"))
    data["spec"]["simulation"]["powerflowBackend"] = backend_id
    project_file.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return target


def _registry_with_host_backend() -> PowerFlowBackendRegistry:
    from gridalyn.simulation.backends.contract import PowerFlowBackendDescriptor
    from gridalyn.simulation.backends.pandapower_native import PandapowerNativeBackend
    from gridalyn.simulation.backends.registry import (
        PowerFlowBackendRegistry,
        register_powerflow_backend_extension,
    )

    registry = PowerFlowBackendRegistry()
    registry.register(PandapowerNativeBackend, source="core", version="3.1.2")
    # The host slot goes through the PUBLIC host API so the gate exercises the
    # same source-marking path a real embedder uses. The factory is never
    # invoked by provenance -- create() is never called here -- it only
    # satisfies the registration shape.
    register_powerflow_backend_extension(
        PandapowerNativeBackend,
        descriptor=PowerFlowBackendDescriptor(
            backend_id="host_backend_probe",
            name="Probe host backend",
        ),
        registry=registry,
        version="2.0.0",
    )
    return registry


class TestExtensionCompletenessGate(unittest.TestCase):
    """The "never silent" rule as a gate (Phase 16, plan 16-03).

    An extension that serves a role MUST be named in provenance — a role
    resolved through an extension that leaves no ``extension_id`` trace is a
    red build, not quiet drift. Mutation-verified: removing the 16-02 wiring
    from ``_powerflow_backend_provenance`` turns this red.
    """

    def test_extension_served_role_is_never_silent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = _grid_study_declaring_backend(tmp, "host_backend_probe")
            with mock.patch(
                "gridalyn.simulation.backends.registry"
                ".default_powerflow_backend_registry",
                return_value=_registry_with_host_backend(),
            ):
                run_workflow(target, dry_run=True)
                manifest_path = (
                    target / "outputs" / "manifests" / "project_run_manifest.json"
                )
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        backend = manifest["provenance"]["powerflow_backend"]
        self.assertEqual(
            "host_backend_probe",
            backend.get("extension_id"),
            "a role served by an extension must name the extension; "
            "provenance.powerflow_backend.extension_id is missing",
        )
        self.assertEqual("host", backend.get("extension_source"))

    def test_core_only_role_stays_silent(self) -> None:
        # The other side of the gate: a shipped backend is not an extension,
        # and must NOT be branded as one (R7 byte-identical manifests).
        with tempfile.TemporaryDirectory() as tmp:
            backend = _run_manifest(tmp)["provenance"]["powerflow_backend"]
        self.assertNotIn("extension_id", backend)
        self.assertNotIn("extension_source", backend)

    def test_by_stage_extension_is_never_silent(self) -> None:
        # Review cycle 2 (W1): a stage override served by an extension must
        # record its identity in by_stage, not only the study default path.
        import yaml

        with tempfile.TemporaryDirectory() as tmp:
            target = _grid_study_declaring_backend(tmp, "host_backend_probe")
            project_file = target / "project.yaml"
            data = yaml.safe_load(project_file.read_text(encoding="utf-8"))
            data["spec"]["simulation"]["powerflowBackendByStage"] = {
                "prepare_workspace": "host_backend_probe"
            }
            project_file.write_text(
                yaml.safe_dump(data, sort_keys=False), encoding="utf-8"
            )
            with mock.patch(
                "gridalyn.simulation.backends.registry"
                ".default_powerflow_backend_registry",
                return_value=_registry_with_host_backend(),
            ):
                run_workflow(target, dry_run=True)
                manifest_path = (
                    target / "outputs" / "manifests" / "project_run_manifest.json"
                )
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        backend = manifest["provenance"]["powerflow_backend"]
        stage = backend["by_stage"]["prepare_workspace"]
        self.assertEqual("host_backend_probe", stage["extension_id"])
        self.assertEqual("host", stage["extension_source"])
        self.assertEqual("2.0.0", stage["extension_version"])

    def test_core_by_stage_override_stays_silent(self) -> None:
        # Review cycle 2 (inverse of the by_stage gate): a stage override that
        # names a SHIPPED backend records no extension keys, so R7 holds on
        # the by_stage path too.
        import yaml

        with tempfile.TemporaryDirectory() as tmp:
            target = _grid_study_declaring_backend(tmp, PANDAPOWER_NATIVE_BACKEND_ID)
            project_file = target / "project.yaml"
            data = yaml.safe_load(project_file.read_text(encoding="utf-8"))
            data["spec"]["simulation"]["powerflowBackendByStage"] = {
                "prepare_workspace": PANDAPOWER_NATIVE_BACKEND_ID
            }
            project_file.write_text(
                yaml.safe_dump(data, sort_keys=False), encoding="utf-8"
            )
            run_workflow(target, dry_run=True)
            manifest_path = (
                target / "outputs" / "manifests" / "project_run_manifest.json"
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        stage = manifest["provenance"]["powerflow_backend"]["by_stage"][
            "prepare_workspace"
        ]
        self.assertEqual(PANDAPOWER_NATIVE_BACKEND_ID, stage["backend_id"])
        self.assertNotIn("extension_id", stage)
        self.assertNotIn("extension_source", stage)
        self.assertNotIn("extension_version", stage)

    def test_host_backend_without_version_has_no_extension_version_key(self) -> None:
        # Review cycle 2 (S8): extension_id/extension_source are recorded even
        # when the host registration carries no version; the version key is
        # absent, not null.
        from gridalyn.simulation.backends.contract import PowerFlowBackendDescriptor
        from gridalyn.simulation.backends.pandapower_native import (
            PandapowerNativeBackend,
        )
        from gridalyn.simulation.backends.registry import (
            PowerFlowBackendRegistry,
            register_powerflow_backend_extension,
        )

        registry = PowerFlowBackendRegistry()
        registry.register(PandapowerNativeBackend, source="core")
        register_powerflow_backend_extension(
            PandapowerNativeBackend,
            descriptor=PowerFlowBackendDescriptor(
                backend_id="host_no_version_probe",
                name="Host backend without a version",
            ),
            registry=registry,
        )
        with tempfile.TemporaryDirectory() as tmp:
            target = _grid_study_declaring_backend(tmp, "host_no_version_probe")
            with mock.patch(
                "gridalyn.simulation.backends.registry"
                ".default_powerflow_backend_registry",
                return_value=registry,
            ):
                run_workflow(target, dry_run=True)
                manifest_path = (
                    target / "outputs" / "manifests" / "project_run_manifest.json"
                )
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        backend = manifest["provenance"]["powerflow_backend"]
        self.assertEqual("host_no_version_probe", backend["extension_id"])
        self.assertEqual("host", backend["extension_source"])
        self.assertNotIn("extension_version", backend)

    def test_manifest_extensions_block_reflects_the_registered_extension(self) -> None:
        # Review cycle 2 (S4): pins the composition _build_provenance ->
        # _extensions_provenance -> extension_provenance. Hardcoding
        # "extensions": [] in the runner (dropping the real call) turns this
        # red. The process-global DEFAULT_REGISTRY is not mutated -- the
        # source snapshot is patched, matching the empty-case test.
        row = {
            "extension_id": "manifest_probe_ext",
            "role": "data_source",
            "source": "host",
            "contract_version": "1",
        }
        with mock.patch(
            "gridalyn.foundation.platform.extensions.extension_provenance",
            return_value=[row],
        ):
            with tempfile.TemporaryDirectory() as tmp:
                extensions = _run_manifest(tmp)["provenance"]["extensions"]
        self.assertEqual([row], extensions)


class TestBackendExtensionProvenance(unittest.TestCase):
    """Role-level identity: WHICH extension served the backend role (16-02)."""

    def test_core_backend_has_no_extension_identity_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            backend = _run_manifest(tmp)["provenance"]["powerflow_backend"]
        self.assertNotIn("extension_id", backend)
        self.assertNotIn("extension_source", backend)
        self.assertNotIn("extension_version", backend)

    def test_host_backend_records_extension_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = _grid_study_declaring_backend(tmp, "host_backend_probe")
            with mock.patch(
                "gridalyn.simulation.backends.registry"
                ".default_powerflow_backend_registry",
                return_value=_registry_with_host_backend(),
            ):
                run_workflow(target, dry_run=True)
                manifest_path = (
                    target / "outputs" / "manifests" / "project_run_manifest.json"
                )
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        backend = manifest["provenance"]["powerflow_backend"]
        self.assertEqual("host_backend_probe", backend["backend_id"])
        self.assertEqual("host_backend_probe", backend["extension_id"])
        self.assertEqual("host", backend["extension_source"])
        self.assertEqual("2.0.0", backend["extension_version"])


if __name__ == "__main__":
    unittest.main()
