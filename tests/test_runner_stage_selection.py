"""Tests for partial workflow runs and runner progress output."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gridalyn.projects import init_project, load_project, run_workflow
from gridalyn.projects.runner import select_stages


def _grid_study_project(tmp: str) -> Path:
    target = Path(tmp) / "my_case"
    init_project(target, name="my_case", template="grid-study")
    return target


class TestSelectStages(unittest.TestCase):
    def test_includes_transitive_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = _grid_study_project(tmp)
            project = load_project(target)

            selected = select_stages(project, ["write_summary_report"])

            self.assertEqual(
                [stage.id for stage in selected],
                ["prepare_workspace", "write_summary_report"],
            )

    def test_unknown_stage_lists_available_stages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = _grid_study_project(tmp)
            project = load_project(target)

            with self.assertRaises(ValueError) as ctx:
                select_stages(project, ["does_not_exist"])

            message = str(ctx.exception)
            self.assertIn("does_not_exist", message)
            self.assertIn("available:", message)
            self.assertIn("prepare_workspace", message)


class TestPartialRun(unittest.TestCase):
    def test_stage_filter_runs_only_requested_closure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = _grid_study_project(tmp)

            executed = run_workflow(target, stages=["prepare_workspace"])

            self.assertEqual(executed, ["prepare_workspace"])
            manifest_path = target / "outputs" / "manifests" / "project_run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["stage_filter"], ["prepare_workspace"])
            self.assertEqual(manifest["status"], "completed")

    def test_full_run_has_no_stage_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = _grid_study_project(tmp)

            executed = run_workflow(target)

            self.assertEqual(executed, ["prepare_workspace", "write_summary_report"])
            manifest_path = target / "outputs" / "manifests" / "project_run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertNotIn("stage_filter", manifest)


if __name__ == "__main__":
    unittest.main()
