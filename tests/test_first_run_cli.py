"""First-run CLI truth: doctor, quickstart, and generated templates.

A researcher's first contact with the CLI happens on a machine that may have
no checkout at all: ``gridalyn doctor`` in an arbitrary directory,
``gridalyn quickstart`` in a venv without the ``sim`` extra, and a project
generated from a scaffold template. Three defects broke that first contact:

- doctor applied gridalyn's own workspace checks to whatever ``--root`` named
  and exited 1 outside a checkout, reporting nothing actionable;
- quickstart preflighted the ``sim`` capability (lightsim2grid) although the
  demo imports only pandapower, a base dependency;
- templates generated the deprecated bare ``command: python`` form, which
  resolves against ``PATH`` and dies with exit 127 on ``python3``-only
  systems (see ``tests/test_runner_interpreter.py``).
"""

from __future__ import annotations

import contextlib
import inspect
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

from gridalyn.interfaces.cli import gridalyn as gridalyn_cli
from gridalyn.projects.api import init_project
from gridalyn.projects.templates import TEMPLATES

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _run_doctor(root: Path) -> tuple[int, dict[str, Any]]:
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        exit_code = gridalyn_cli.main(["doctor", "--root", str(root)])
    return exit_code, json.loads(stdout.getvalue())


class TestDoctorOutsideAWorkspace(unittest.TestCase):
    """Finding #23: doctor must succeed where there is no workspace."""

    def test_exit_zero_and_workspace_found_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            exit_code, payload = _run_doctor(Path(tmp))

        self.assertEqual(0, exit_code)
        self.assertIs(False, payload["workspace"]["found"])

    def test_installation_sections_survive_without_a_workspace(self) -> None:
        # The installation is healthy; only the workspace is absent. The
        # payload must still let a user check python, gridalyn version and
        # optional capabilities.
        with tempfile.TemporaryDirectory() as tmp:
            _exit_code, payload = _run_doctor(Path(tmp))

        self.assertTrue(payload["valid"])
        self.assertIn("version", payload["python"])
        self.assertIn("executable", payload["python"])
        self.assertIn("version", payload["gridalyn"])
        self.assertIn("optional_capabilities", payload)

    def test_note_names_both_remedies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _exit_code, payload = _run_doctor(Path(tmp))

        note = payload["workspace"]["note"]
        self.assertIn("gridalyn quickstart", note)
        self.assertIn("--root", note)


class TestDoctorInsideTheWorkspace(unittest.TestCase):
    """With a workspace present, doctor keeps its full workspace section."""

    def test_workspace_section_reports_found_true(self) -> None:
        _exit_code, payload = _run_doctor(_REPO_ROOT)

        self.assertIs(True, payload["workspace"]["found"])
        # The pre-existing shape survives: validation ran and reported.
        self.assertIn("valid", payload["workspace"])
        self.assertIn("failed_checks", payload["workspace"])
        self.assertIn("summary", payload["workspace"])


class TestQuickstartCapabilityGate(unittest.TestCase):
    """Finding #24: quickstart must not preflight capabilities it never uses."""

    def test_handler_has_no_capability_preflight(self) -> None:
        source = inspect.getsource(gridalyn_cli._quickstart)

        self.assertNotIn('require_capabilities("sim"', source)
        # The fix is removal, not replacement: no preflight of any kind.
        self.assertNotIn("require_capabilities", source)


class TestTemplatesEmitTheQuotedPlaceholderForm(unittest.TestCase):
    """Finding #26: generated workflows use ``command: "{python} …"``.

    Unquoted ``{python}`` is a YAML flow mapping, so the quoting is
    load-bearing: the parsed command must come back as a string carrying the
    placeholder that ``_resolve_interpreter`` substitutes.
    """

    def _generated_workflow_text(self, template_name: str, base: Path) -> str:
        target = base / template_name.replace("-", "_")
        created = init_project(target, template=template_name)
        return (Path(created.root) / "workflow.yaml").read_text(encoding="utf-8")

    def test_generated_projects_use_the_placeholder_in_every_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for template_name in sorted(TEMPLATES):
                with self.subTest(template=template_name):
                    text = self._generated_workflow_text(template_name, Path(tmp))
                    document = yaml.safe_load(text)
                    stages = document["spec"]["stages"]

                    # grep -c semantics: count matching lines exactly.
                    bare_lines = [
                        line for line in text.splitlines() if "command: python " in line
                    ]
                    quoted_lines = [
                        line
                        for line in text.splitlines()
                        if 'command: "{python} ' in line
                    ]
                    self.assertEqual([], bare_lines)
                    self.assertEqual(len(stages), len(quoted_lines))

                    for stage in stages:
                        with self.subTest(stage=stage["id"]):
                            command = stage["command"]
                            self.assertIsInstance(command, str)
                            self.assertTrue(
                                command.startswith("{python} "),
                                f"stage command lost the placeholder: {command!r}",
                            )


if __name__ == "__main__":
    unittest.main()
