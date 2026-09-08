"""The run manifest is written per stage, and a partial run never erases a full one.

Two defects the flagship paid for in September 2026:

* The manifest was written ONCE, in ``run_project``'s ``finally``. A six-hour
  run had no record on disk until it ended, and a hard kill (SIGKILL, OOM,
  power) discarded every completed stage's timing along with the whole run.
* A ``--stage`` run wrote its manifest to the same path as a full run and
  replaced it. A 13-stage recovery run erased the only record of a 20-stage
  run; the timings survived solely because stderr had been tee'd to a file.

These tests pin the two behaviours that close them.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from gridalyn.projects.loader import load_project
from gridalyn.projects.runner import run_project

_PROJECT = """
apiVersion: gridalyn.io/v1alpha1
kind: StudyProject
metadata:
  name: persistence_project
  version: 0.1.0
spec:
  problem:
    type: test_problem
    dataset: test_dataset
    environment: test_environment
    objective: Pin manifest persistence.
    model:
      type: workflow_model
      name: persistence_workflow
    scenarios:
      - id: baseline
        role: test_baseline
  inputs: {}
  artifacts: {}
  workflow:
    file: workflow.yaml
  validation: {}
""".strip()


def _write_project(root: Path, second_command: str) -> Path:
    """Write a two-stage project whose second stage runs ``second_command``."""
    (root / "workflow.yaml").write_text(
        f"""
apiVersion: gridalyn.io/v1alpha1
kind: Workflow
metadata:
  name: persistence_workflow
spec:
  stages:
    - id: build
      command: echo build
    - id: validate
      needs: [build]
      command: {second_command!r}
""".strip(),
        encoding="utf-8",
    )
    (root / "project.yaml").write_text(_PROJECT, encoding="utf-8")
    return root / "outputs" / "manifests" / "project_run_manifest.json"


def _read(path: Path) -> dict:  # type: ignore[type-arg]
    return json.loads(path.read_text(encoding="utf-8"))


class ManifestPersistenceTests(unittest.TestCase):
    def test_manifest_is_on_disk_before_the_next_stage_starts(self) -> None:
        """Stage 2 inspects the manifest and fails unless stage 1 is already recorded.

        This is checked from INSIDE the run, by the stage itself, so it proves
        the per-stage write happened before the next subprocess was spawned --
        not merely that a manifest exists after the run.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = root / "outputs" / "manifests" / "project_run_manifest.json"
            check = root / "check.py"
            check.write_text(
                "import json, sys\n"
                f"m = json.load(open({str(manifest_path)!r}))\n"
                "first = m['stages'][0]\n"
                "ok = (m['status'] == 'running' and first['id'] == 'build'\n"
                "      and first['status'] == 'completed' and first['exit_code'] == 0\n"
                "      and first['ended_at'] is not None)\n"
                "sys.exit(0 if ok else 3)\n",
                encoding="utf-8",
            )
            _write_project(root, f"{{python}} {check}")
            project = load_project(root / "project.yaml")

            executed = run_project(project, manifest_path=manifest_path)

            self.assertEqual(executed, ["build", "validate"])
            manifest = _read(manifest_path)
            self.assertEqual(manifest["status"], "completed")
            self.assertEqual(
                [s["status"] for s in manifest["stages"]], ["completed"] * 2
            )

    def test_a_failed_stage_leaves_the_completed_ones_on_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = _write_project(root, "exit 7")
            project = load_project(root / "project.yaml")
            with self.assertRaises(subprocess.CalledProcessError):
                run_project(project, manifest_path=manifest_path)
            manifest = _read(manifest_path)
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual(manifest["stages"][0]["status"], "completed")
            self.assertEqual(manifest["stages"][1]["status"], "failed")
            self.assertEqual(manifest["stages"][1]["exit_code"], 7)


class PartialRunProtectionTests(unittest.TestCase):
    def test_a_partial_run_does_not_overwrite_a_full_runs_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = _write_project(root, "echo validate")
            project = load_project(root / "project.yaml")
            run_project(project, manifest_path=manifest_path)
            full_before = _read(manifest_path)
            self.assertNotIn("stage_filter", full_before)
            self.assertEqual(len(full_before["stages"]), 2)

            run_project(project, manifest_path=manifest_path, stages=["build"])

            full_after = _read(manifest_path)
            partial_path = manifest_path.with_name("project_run_manifest.partial.json")
            self.assertTrue(partial_path.is_file(), "the partial run got no manifest")
            partial = _read(partial_path)
            # The full run's record is intact...
            self.assertEqual(full_after["stages"], full_before["stages"])
            self.assertEqual(full_after["started_at"], full_before["started_at"])
            self.assertNotIn("stage_filter", full_after)
            # ...and now says what was rewritten after it, by which run.
            since = full_after["partial_runs_since"]
            self.assertEqual(len(since), 1)
            self.assertEqual(since[0]["stages"], ["build"])
            self.assertEqual(since[0]["manifest"], str(partial_path))
            self.assertEqual(since[0]["started_at"], partial["started_at"])
            # The partial run knows it is secondary.
            self.assertEqual(partial["stage_filter"], ["build"])
            self.assertEqual(partial["primary_manifest"], str(manifest_path))
            self.assertEqual([s["id"] for s in partial["stages"]], ["build"])

    def test_a_new_full_run_replaces_the_primary_and_clears_the_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = _write_project(root, "echo validate")
            project = load_project(root / "project.yaml")
            run_project(project, manifest_path=manifest_path)
            run_project(project, manifest_path=manifest_path, stages=["build"])
            self.assertIn("partial_runs_since", _read(manifest_path))

            run_project(project, manifest_path=manifest_path)

            fresh = _read(manifest_path)
            self.assertNotIn("partial_runs_since", fresh)
            self.assertNotIn("stage_filter", fresh)
            self.assertEqual(len(fresh["stages"]), 2)

    def test_a_partial_run_with_nothing_coherent_to_protect_writes_in_place(
        self,
    ) -> None:
        """No prior full run: the partial manifest goes to the default path, as before."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = _write_project(root, "echo validate")
            project = load_project(root / "project.yaml")
            run_project(project, manifest_path=manifest_path, stages=["build"])
            self.assertTrue(manifest_path.is_file())
            self.assertFalse(
                manifest_path.with_name("project_run_manifest.partial.json").exists()
            )
            self.assertEqual(_read(manifest_path)["stage_filter"], ["build"])

    def test_a_failed_full_run_is_not_protected(self) -> None:
        """Only a COMPLETED full run is coherent; a failed one is overwritten as before."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_path = _write_project(root, "exit 1")
            project = load_project(root / "project.yaml")
            with self.assertRaises(subprocess.CalledProcessError):
                run_project(project, manifest_path=manifest_path)
            self.assertEqual(_read(manifest_path)["status"], "failed")

            run_project(project, manifest_path=manifest_path, stages=["build"])

            self.assertEqual(_read(manifest_path)["stage_filter"], ["build"])
            self.assertFalse(
                manifest_path.with_name("project_run_manifest.partial.json").exists()
            )


class DeclaredOutputTests(unittest.TestCase):
    """``outputs:`` is a contract: a stage that declares one must produce it."""

    def _project(self, root: Path, command: str, outputs: list[str]) -> Path:
        lines = [
            "apiVersion: gridalyn.io/v1alpha1",
            "kind: Workflow",
            "metadata:",
            "  name: persistence_workflow",
            "spec:",
            "  stages:",
            "    - id: build",
            f"      command: {command!r}",
        ]
        if outputs:
            lines.append("      outputs:")
            lines.extend(f"        - {o}" for o in outputs)
        (root / "workflow.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (root / "project.yaml").write_text(_PROJECT, encoding="utf-8")
        return root / "outputs" / "manifests" / "project_run_manifest.json"

    def test_a_produced_declared_output_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mp = self._project(
                root,
                "mkdir -p outputs/json && echo '{}' > outputs/json/x.json",
                ["outputs/json/x.json"],
            )
            self.assertEqual(
                run_project(load_project(root / "project.yaml"), manifest_path=mp),
                ["build"],
            )

    def test_a_declared_output_that_is_not_produced_fails_the_run_by_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mp = self._project(root, "echo STUB", ["outputs/json/never.json"])
            with self.assertRaises(FileNotFoundError) as ctx:
                run_project(load_project(root / "project.yaml"), manifest_path=mp)
            self.assertIn("'build'", str(ctx.exception))
            self.assertIn("outputs/json/never.json", str(ctx.exception))
            self.assertIn("Remediation", str(ctx.exception))
            manifest = _read(mp)
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual(manifest["stages"][0]["status"], "failed")
            self.assertEqual(manifest["stages"][0]["error"], "declared output missing")

    def test_a_stage_declaring_no_outputs_is_not_checked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mp = self._project(root, "echo nothing", [])
            self.assertEqual(
                run_project(load_project(root / "project.yaml"), manifest_path=mp),
                ["build"],
            )
