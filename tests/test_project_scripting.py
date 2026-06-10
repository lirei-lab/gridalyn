"""Tests for the boilerplate-free project scripting helpers."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from gridalyn.foundation.platform.reports import read_json_report, validate_report
from gridalyn.projects import init_project
from gridalyn.projects.scripting import ProjectScript, find_project_root, project_script


class TestFindProjectRoot(unittest.TestCase):
    def test_finds_project_yaml_in_parent_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "my_case"
            init_project(target, name="my_case")

            self.assertEqual(find_project_root(target), target)
            self.assertEqual(find_project_root(target / "scripts"), target)

    def test_raises_with_guidance_when_no_project_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError) as ctx:
                find_project_root(tmp)
            self.assertIn("project.yaml", str(ctx.exception))
            self.assertIn("root=", str(ctx.exception))


class TestProjectScript(unittest.TestCase):
    def _make_script(self, tmp: str) -> ProjectScript:
        target = Path(tmp) / "my_case"
        init_project(target, name="my_case")
        return project_script(target)

    def test_loads_project_and_prepares_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = self._make_script(tmp)

            self.assertEqual(script.name, "my_case")
            self.assertEqual(script.version, "0.1.0")
            self.assertTrue(script.data_dir.is_dir())
            self.assertTrue(script.figures_dir.is_dir())
            self.assertTrue(script.reports_dir.is_dir())
            self.assertTrue(script.manifests_dir.is_dir())
            self.assertTrue(script.operations_dir.is_dir())
            self.assertIn("MPLCONFIGDIR", os.environ)

    def test_path_creates_parent_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = self._make_script(tmp)

            target = script.path("outputs/data/nested/result.csv")

            self.assertTrue(target.parent.is_dir())
            self.assertEqual(target, script.root / "outputs/data/nested/result.csv")

    def test_write_report_prefills_project_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = self._make_script(tmp)

            payload = script.write_report("sample_report", summary={"ready": True})

            report_path = script.reports_dir / "sample_report.json"
            self.assertTrue(report_path.exists())
            stored = read_json_report(report_path)
            self.assertEqual(validate_report(stored), [])
            self.assertEqual(payload["report_id"], "sample_report")
            self.assertEqual(payload["source_domain"], "my_case")
            self.assertEqual(payload["project"], {"name": "my_case"})

    def test_write_report_honours_explicit_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = self._make_script(tmp)
            explicit = script.reports_dir / "custom_name.json"

            script.write_report("sample_report", path=explicit, summary={"ready": True})

            self.assertTrue(explicit.exists())

    def test_file_reference_is_relative_to_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = self._make_script(tmp)
            artifact = script.data_dir / "table.csv"
            artifact.write_text("a,b\n1,2\n", encoding="utf-8")

            reference = script.file_reference(artifact)

            self.assertEqual(reference["path"], "outputs/data/table.csv")
            self.assertIn("sha256", reference)

    def test_input_reports_missing_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = self._make_script(tmp)

            with self.assertRaises(ValueError):
                script.input("doesNotExist")


if __name__ == "__main__":
    unittest.main()
