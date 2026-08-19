"""Tests that stage commands are bound to the interpreter running the study.

A bare ``python`` in a stage command resolves against ``PATH`` under
``shell=True``. On a venv or a ``python3``-only system there is no such
executable and every governed stage dies with exit 127, which is why the whole
project suite was red for environmental reasons.

Two mechanisms fix that: the explicit ``{python}`` placeholder the shipped
workflows declare, and a compatibility fallback for a leading bare ``python``.
The load-bearing assertions here are the *independence* ones — if the fallback
could quietly rescue a broken placeholder (or vice versa), a regression in
either mechanism would never surface.
"""

from __future__ import annotations

import re
import shlex
import sys
import unittest
import unittest.mock
from pathlib import Path

import yaml

from gridalyn.projects.runner import (
    _BARE_INTERPRETER_TOKEN,
    _INTERPRETER_PLACEHOLDER,
    _resolve_interpreter,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOWS = sorted((_REPO_ROOT / "projects").glob("*/workflow.yaml"))
_QUOTED_EXECUTABLE = shlex.quote(sys.executable)


class TestExplicitPlaceholder(unittest.TestCase):
    """Assertion 1: ``{python}`` is substituted with ``sys.executable``."""

    def test_placeholder_is_substituted(self) -> None:
        resolved = _resolve_interpreter("{python} -m gridalyn.interfaces.cli.project")

        self.assertEqual(
            f"{_QUOTED_EXECUTABLE} -m gridalyn.interfaces.cli.project", resolved
        )
        self.assertIn(sys.executable, resolved)
        self.assertNotIn(_INTERPRETER_PLACEHOLDER, resolved)

    def test_executable_is_shell_quoted(self) -> None:
        # The command goes through ``shell=True``; an unquoted path containing a
        # space would be re-parsed into two argv entries.
        self.assertTrue(
            _resolve_interpreter("{python} x.py").startswith(_QUOTED_EXECUTABLE)
        )

    def test_arguments_after_the_placeholder_survive_verbatim(self) -> None:
        tail = " prepare-workspace projects/ev_hosting_flex"
        resolved = _resolve_interpreter(
            "{python} -m gridalyn.interfaces.cli.project" + tail
        )

        self.assertTrue(resolved.endswith(tail))


class TestBareTokenFallback(unittest.TestCase):
    """Assertion 2: a leading bare ``python`` token is substituted."""

    def test_leading_token_is_substituted(self) -> None:
        resolved = _resolve_interpreter("python scripts/run_minimal_powerflow.py")

        self.assertEqual(
            f"{_QUOTED_EXECUTABLE} scripts/run_minimal_powerflow.py", resolved
        )

    def test_leading_whitespace_and_spacing_are_preserved(self) -> None:
        self.assertEqual(
            f"  {_QUOTED_EXECUTABLE}  -c 'pass'",
            _resolve_interpreter("  python  -c 'pass'"),
        )


class TestNonLeadingPythonIsUntouched(unittest.TestCase):
    """Assertion 3: only the leading token may be rewritten."""

    def test_python_as_an_argument_is_untouched(self) -> None:
        command = "foo --flag python bar"

        self.assertEqual(command, _resolve_interpreter(command))

    def test_python_inside_a_path_is_untouched(self) -> None:
        command = "sh scripts/python_helper.py"

        self.assertEqual(command, _resolve_interpreter(command))

    def test_a_launcher_prefix_is_untouched(self) -> None:
        # ``uv run python …`` is used by the two heavy studies. Rewriting the
        # non-leading ``python`` there would break the launcher contract.
        command = "uv run python projects/ev_hosting_flex/scripts/pipeline/x.py"

        self.assertEqual(command, _resolve_interpreter(command))

    def test_a_token_merely_prefixed_with_python_is_untouched(self) -> None:
        command = "python3 -m pytest"

        self.assertEqual(command, _resolve_interpreter(command))


class TestUnrelatedCommandsAreUnchanged(unittest.TestCase):
    """Assertion 4: a command using neither form is returned unchanged."""

    def test_echo_stub_is_unchanged(self) -> None:
        command = 'echo "STUB build_study_reports — canonical study report pending"'

        self.assertEqual(command, _resolve_interpreter(command))

    def test_empty_command_is_unchanged(self) -> None:
        self.assertEqual("", _resolve_interpreter(""))


class TestMechanismIndependence(unittest.TestCase):
    """Assertion 5: neither mechanism may mask a defect in the other.

    If the fallback could rescue a command whose placeholder failed to
    substitute, a broken placeholder would ship silently — the exact failure
    mode this suite exists to prevent.
    """

    def test_placeholder_resolves_where_the_fallback_cannot_fire(self) -> None:
        # The leading token is ``echo``, so the fallback branch is
        # definitionally inapplicable: only the placeholder can substitute here.
        command = "echo {python} --version"
        self.assertNotEqual(_BARE_INTERPRETER_TOKEN, command.split(None, 1)[0])

        resolved = _resolve_interpreter(command)

        self.assertEqual(f"echo {_QUOTED_EXECUTABLE} --version", resolved)
        # Control: strip the placeholder and nothing else resolves the command.
        self.assertEqual("echo --version", _resolve_interpreter("echo --version"))

    def test_fallback_resolves_where_no_placeholder_exists(self) -> None:
        command = "python scripts/build_der_feeder.py"
        self.assertNotIn(_INTERPRETER_PLACEHOLDER, command)
        self.assertNotIn("{", command)  # no placeholder of any shape

        self.assertIn(sys.executable, _resolve_interpreter(command))

    def test_disabling_the_placeholder_does_not_disable_the_fallback(self) -> None:
        # Mutate the placeholder to a token that cannot occur, proving the
        # fallback substitution is not secretly the placeholder branch.
        with unittest.mock.patch(
            "gridalyn.projects.runner._INTERPRETER_PLACEHOLDER",
            "{never-occurs-in-any-command}",
        ):
            self.assertIn(sys.executable, _resolve_interpreter("python a.py"))
            # …and the real placeholder is now inert, so it falls through
            # unchanged rather than being rescued by the fallback.
            self.assertEqual("echo {python}", _resolve_interpreter("echo {python}"))

    def test_disabling_the_fallback_does_not_disable_the_placeholder(self) -> None:
        # Mutate the bare token to something no command starts with, proving the
        # placeholder substitution does not route through the fallback.
        with unittest.mock.patch(
            "gridalyn.projects.runner._BARE_INTERPRETER_TOKEN",
            "never-a-leading-token",
        ):
            self.assertIn(sys.executable, _resolve_interpreter("{python} a.py"))
            # …and the bare form is now inert.
            self.assertEqual("python a.py", _resolve_interpreter("python a.py"))


class TestShippedWorkflowsUseTheExplicitForm(unittest.TestCase):
    """Assertion 6: no shipped workflow relies on the fallback.

    The fallback exists for user-authored and template-generated contracts. The
    contracts this repository ships are explicit, so a change to the fallback
    can never silently alter a governed study — and this test is what keeps the
    migration from quietly reverting.
    """

    def test_eight_workflows_are_discovered(self) -> None:
        self.assertEqual(8, len(_WORKFLOWS), [str(p) for p in _WORKFLOWS])

    def test_no_shipped_command_has_a_bare_leading_python_token(self) -> None:
        offenders: list[str] = []
        for path in _WORKFLOWS:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
            for stage in document["spec"]["stages"]:
                command = stage["command"]
                if command.split(None, 1)[:1] == [_BARE_INTERPRETER_TOKEN]:
                    relative = path.relative_to(_REPO_ROOT).as_posix()
                    offenders.append(f"{relative}::{stage['id']}: {command}")

        self.assertEqual([], offenders)

    def test_no_shipped_command_line_uses_the_bare_form_textually(self) -> None:
        # Belt-and-braces on the raw text, so a quoting change cannot hide a
        # bare command from the parsed check above.
        pattern = re.compile(rf"^\s*command:\s*{_BARE_INTERPRETER_TOKEN}\s", re.M)
        offenders = [
            path.relative_to(_REPO_ROOT).as_posix()
            for path in _WORKFLOWS
            if pattern.search(path.read_text(encoding="utf-8"))
        ]

        self.assertEqual([], offenders)

    def test_every_shipped_stage_command_resolves_to_a_real_interpreter(self) -> None:
        # No stage may reach the shell still carrying an unsubstituted
        # placeholder, and none may depend on a bare ``python`` on PATH.
        for path in _WORKFLOWS:
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
            for stage in document["spec"]["stages"]:
                resolved = _resolve_interpreter(stage["command"])
                with self.subTest(workflow=path.name, stage=stage["id"]):
                    self.assertNotIn(_INTERPRETER_PLACEHOLDER, resolved)
                    self.assertNotEqual(
                        _BARE_INTERPRETER_TOKEN, resolved.split(None, 1)[:1]
                    )

    def test_the_declared_placeholder_count_is_pinned(self) -> None:
        declared = sum(
            path.read_text(encoding="utf-8").count(_INTERPRETER_PLACEHOLDER)
            for path in _WORKFLOWS
        )

        # 32 (Phase 19) + 20 ev_hosting_flex pipeline stages converted to
        # {python} -m in Phase 20 (plan 20-02) + 1 export_twin_network_model
        # stage added in Phase 31 (Milestone 14).
        self.assertEqual(53, declared)


if __name__ == "__main__":
    unittest.main()
