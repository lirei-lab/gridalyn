"""A run fingerprints its artifacts at close, and a reader can tell when they drift.

The manifest said which commit ran and which stages; nothing tied the files on
disk to it afterwards. Two things rewrote flagship artifacts without a trace
in September 2026: a ``--stage`` run (now recorded under ``partial_runs_since``)
and the plain test suite, whose annual byte-stability seal regenerates a subset
whenever outputs are present. These tests pin the fingerprint and the check
that makes the attestation ``syntgrid-qgr.1`` asked for actually checkable.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

from gridalyn.projects.loader import load_project
from gridalyn.projects.runner import run_project

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from stage_profile import drifted_artifacts, profile_project  # noqa: E402

_PROJECT = """
apiVersion: gridalyn.io/v1alpha1
kind: StudyProject
metadata:
  name: attest_project
  version: 0.1.0
spec:
  problem:
    type: test_problem
    dataset: test_dataset
    environment: test_environment
    objective: Pin artifact fingerprinting.
    model:
      type: workflow_model
      name: attest_workflow
    scenarios:
      - id: baseline
        role: test_baseline
  inputs: {}
  artifacts: {}
  workflow:
    file: workflow.yaml
  validation: {}
""".strip()


def _project_writing_one_artifact(root: Path) -> Path:
    """A one-stage project whose stage writes outputs/json/result.json."""
    writer = root / "write.py"
    writer.write_text(
        "import json, pathlib\n"
        "p = pathlib.Path('outputs/json'); p.mkdir(parents=True, exist_ok=True)\n"
        "(p / 'result.json').write_text(json.dumps({'value': 1}))\n",
        encoding="utf-8",
    )
    (root / "workflow.yaml").write_text(
        f"""
apiVersion: gridalyn.io/v1alpha1
kind: Workflow
metadata:
  name: attest_workflow
spec:
  stages:
    - id: produce
      command: {f"{{python}} {writer}"!r}
""".strip(),
        encoding="utf-8",
    )
    (root / "project.yaml").write_text(_PROJECT, encoding="utf-8")
    return root / "outputs" / "manifests" / "project_run_manifest.json"


class ArtifactFingerprintTests(unittest.TestCase):
    def test_the_manifest_records_every_artifacts_sha256_at_close(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = _project_writing_one_artifact(root)
            run_project(
                load_project(root / "project.yaml"), manifest_path=manifest_path
            )

            manifest = json.loads(manifest_path.read_text())
            recorded = manifest["artifacts"]
            self.assertEqual(list(recorded), ["outputs/json/result.json"])
            actual = hashlib.sha256((root / "outputs/json/result.json").read_bytes())
            self.assertEqual(
                recorded["outputs/json/result.json"]["sha256"], actual.hexdigest()
            )
            self.assertGreater(recorded["outputs/json/result.json"]["bytes"], 0)
            # The manifest does not fingerprint itself.
            self.assertFalse(any(k.startswith("outputs/manifests") for k in recorded))

    def test_a_dry_run_records_no_fingerprints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = _project_writing_one_artifact(root)
            run_project(
                load_project(root / "project.yaml"),
                manifest_path=manifest_path,
                dry_run=True,
            )
            self.assertNotIn("artifacts", json.loads(manifest_path.read_text()))


class DriftDetectionTests(unittest.TestCase):
    def test_a_rewritten_artifact_is_reported_and_an_intact_one_is_not(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = _project_writing_one_artifact(root)
            run_project(
                load_project(root / "project.yaml"), manifest_path=manifest_path
            )
            manifest = json.loads(manifest_path.read_text())

            self.assertEqual(drifted_artifacts(manifest, root), ([], [], 1))
            profile = profile_project(root, workers=2)
            self.assertEqual(profile["coverage"]["artifacts_changed"], [])

            # The failure mode: something other than the run rewrites the file.
            (root / "outputs/json/result.json").write_text(json.dumps({"value": 2}))

            changed, missing, total = drifted_artifacts(manifest, root)
            self.assertEqual(
                (changed, missing, total), (["outputs/json/result.json"], [], 1)
            )
            profile = profile_project(root, workers=2)
            self.assertEqual(
                profile["coverage"]["artifacts_changed"], ["outputs/json/result.json"]
            )

    def test_a_deleted_artifact_is_reported_as_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = _project_writing_one_artifact(root)
            run_project(
                load_project(root / "project.yaml"), manifest_path=manifest_path
            )
            manifest = json.loads(manifest_path.read_text())
            (root / "outputs/json/result.json").unlink()
            self.assertEqual(
                drifted_artifacts(manifest, root), ([], ["outputs/json/result.json"], 1)
            )

    def test_a_manifest_without_fingerprints_reports_nothing(self) -> None:
        """Runs recorded before the fingerprint existed must not read as drifted."""
        self.assertEqual(
            drifted_artifacts({"stages": []}, Path("/nonexistent")), ([], [], 0)
        )
