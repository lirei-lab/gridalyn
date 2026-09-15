"""The workspace root and a study's directory are distinct types (bd 6ns.1).

bd 7rt passed a study's directory where the workspace root was required; the
layout pointed at a path that does not exist and a flagship stage died after
writing 21 MB under a doubled ``projects/<study>/projects/<study>/``. The fix that
followed passed ``script.base_dir`` instead, which equals the workspace root only
for ``pathBase: repo`` studies. ``WorkspaceRoot`` and ``ProjectDir`` make mypy
reject the swap, so these tests pin both the values and that rejection.
"""

from __future__ import annotations

import importlib.util
import os
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from gridalyn.foundation.platform.workspace import ArtifactLayout, find_workspace_root
from gridalyn.projects.scripting import project_script

_REPO_ROOT = Path(__file__).resolve().parents[1]
_REPO_BASED = _REPO_ROOT / "projects" / "ev_hosting_flex"
_PROJECT_BASED = _REPO_ROOT / "projects" / "minimal_grid_project"


class RootValuesTest(unittest.TestCase):
    """The typed properties return the directories they name."""

    def test_workspace_root_is_the_repository_whatever_path_base_says(self) -> None:
        """Both conventions resolve the same workspace root, and never the study."""
        for study in (_REPO_BASED, _PROJECT_BASED):
            with self.subTest(study=study.name):
                script = project_script(study, headless_matplotlib=False)
                self.assertEqual(script.workspace_root, _REPO_ROOT)
                self.assertEqual(
                    script.workspace_root, find_workspace_root(script.root)
                )
                self.assertEqual(script.root, study)
                self.assertNotEqual(script.workspace_root, script.root)

    def test_base_dir_matches_the_workspace_root_only_under_repo(self) -> None:
        """The coincidence the types exist to stop anyone relying on."""
        repo = project_script(_REPO_BASED, headless_matplotlib=False)
        project = project_script(_PROJECT_BASED, headless_matplotlib=False)
        self.assertEqual(repo.base_dir, repo.workspace_root)
        self.assertEqual(project.base_dir, project.root)
        self.assertNotEqual(project.base_dir, project.workspace_root)

    def test_the_layout_still_accepts_a_workspace_root_at_run_time(self) -> None:
        """NewType is identity at run time: nothing that ran before changes."""
        layout = ArtifactLayout(find_workspace_root(_REPO_ROOT))
        self.assertEqual(layout.projects, _REPO_ROOT / "projects")


@unittest.skipIf(importlib.util.find_spec("mypy") is None, "mypy is not installed")
class MypyRejectsTheSwapTest(unittest.TestCase):
    """mypy rejects a study directory where the workspace root is required."""

    def _mypy(self, body: str) -> tuple[int, str]:
        from mypy import api

        with tempfile.TemporaryDirectory() as tmp:
            snippet = Path(tmp) / "snippet.py"
            snippet.write_text(textwrap.dedent(body), encoding="utf-8")
            # Resolve gridalyn from this checkout, not from wherever an editable
            # install happens to point.
            with mock.patch.dict(os.environ, {"MYPYPATH": str(_REPO_ROOT)}):
                out, err, code = api.run(
                    [
                        "--ignore-missing-imports",
                        "--disallow-untyped-defs",
                        # Keep the imported types, report only the snippet.
                        "--follow-imports=silent",
                        "--cache-dir",
                        str(Path(tmp) / "cache"),
                        str(snippet),
                    ]
                )
        return code, out + err

    def test_a_study_directory_is_rejected_as_the_workspace_root(self) -> None:
        """The exact 7rt call, written against the typed API, fails to type-check."""
        code, output = self._mypy(
            """
            from gridalyn.operations.artifacts import (
                materialize_flexibility_operation_artifacts,
            )
            from gridalyn.projects.scripting import project_script


            def stage() -> None:
                script = project_script()
                materialize_flexibility_operation_artifacts(
                    root=script.root, project_id="x", scenario_id="y"
                )
            """
        )
        self.assertNotEqual(code, 0, output)
        self.assertIn('expected "WorkspaceRoot"', output)

    def test_the_workspace_root_type_checks(self) -> None:
        """The control: the correct call is accepted, so the rejection is specific."""
        code, output = self._mypy(
            """
            from gridalyn.operations.artifacts import (
                materialize_flexibility_operation_artifacts,
            )
            from gridalyn.projects.scripting import project_script


            def stage() -> None:
                script = project_script()
                materialize_flexibility_operation_artifacts(
                    root=script.workspace_root, project_id="x", scenario_id="y"
                )
            """
        )
        self.assertNotIn("snippet.py", output)


if __name__ == "__main__":  # pragma: no cover - manual run
    unittest.main()
