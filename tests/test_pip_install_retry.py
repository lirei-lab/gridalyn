"""Gate for the dependency-install retry in ``tools/pip_install_retry.py``.

The tool exists because a cut package fetch reddened six CI jobs in one day,
none of them on a failing test (bd ahx). It is tested here rather than trusted
for the same reason ``tools/ci_main_status.mjs`` is: inline workflow logic
cannot be exercised by the pull request that changes it, and the branch that
matters most is the one that must NOT happen -- a genuine install failure being
retried into three attempts and a timeout instead of failing in seconds.

The fake install below is a real subprocess, not a mock: what the tool has to
classify is a child process's combined output, so a stub that returns a string
would skip the part that broke in production.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from types import ModuleType

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TOOL_PATH = _REPO_ROOT / "tools" / "pip_install_retry.py"

#: The exact error the six measured CI failures carried.
_TRANSIENT_OUTPUT = (
    "ERROR: Could not install packages due to an OSError: "
    "('Connection broken: IncompleteRead(214027 bytes read, 3458 more expected)', "
    "IncompleteRead(214027 bytes read, 3458 more expected))"
)

#: A failure that is this repository's bug, not the network's.
_GENUINE_OUTPUT = "ERROR: No matching distribution found for gridalyn-nonexistent"


def _load_tool() -> ModuleType:
    """Import ``tools/pip_install_retry.py`` without mutating ``sys.path``."""
    spec = importlib.util.spec_from_file_location("pip_install_retry", _TOOL_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - unreachable
        raise ImportError(f"cannot load {_TOOL_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tool = _load_tool()


def _fake_install(message: str, *, exit_code: int, succeed_after: int = 0) -> list[str]:
    """A command that prints ``message`` and exits, as a failing pip would.

    Args:
        message: Text written to stderr, the way pip reports a failure.
        exit_code: Code to exit with while still failing.
        succeed_after: Number of failures before the command starts
            succeeding, counted in a file beside the marker so the count
            survives across processes.

    Returns:
        A command list for ``run_pip_install``'s ``command`` argument.
    """
    script = (
        "import os, sys\n"
        "marker = os.environ['FAKE_INSTALL_MARKER']\n"
        "attempts = 0\n"
        "if os.path.exists(marker):\n"
        "    attempts = int(open(marker).read() or 0)\n"
        "attempts += 1\n"
        "open(marker, 'w').write(str(attempts))\n"
        f"if attempts > {succeed_after}:\n"
        "    print('Successfully installed gridalyn')\n"
        "    sys.exit(0)\n"
        f"sys.stderr.write({message!r})\n"
        f"sys.exit({exit_code})\n"
    )
    return [sys.executable, "-c", script]


class TransientClassificationTest(unittest.TestCase):
    """What counts as the network's fault is a narrow, stated list."""

    def test_the_measured_ci_failure_is_transient(self):
        self.assertTrue(tool.is_transient_failure(_TRANSIENT_OUTPUT))

    def test_a_resolution_failure_is_not_transient(self):
        self.assertFalse(tool.is_transient_failure(_GENUINE_OUTPUT))

    def test_every_marker_is_a_transport_failure(self):
        """No resolver wording may enter the list, whatever it looks like."""
        for marker in tool.TRANSIENT_MARKERS:
            with self.subTest(marker=marker):
                self.assertNotIn("distribution", marker.lower())
                self.assertNotIn("wheel", marker.lower())


class RetryBehaviourTest(unittest.TestCase):
    """The tool retries the cut fetch and nothing else."""

    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory(prefix="pip-retry-"))
        self.marker = Path(self.tmp) / "attempts"
        self.slept: list[float] = []
        self.environ = self.enterContext(
            unittest.mock.patch.dict(
                "os.environ", {"FAKE_INSTALL_MARKER": str(self.marker)}
            )
        )

    def _attempts(self) -> int:
        return int(self.marker.read_text()) if self.marker.exists() else 0

    def test_a_cut_fetch_is_retried_and_the_install_succeeds(self):
        code = tool.run_pip_install(
            ["-e", "."],
            attempts=3,
            delay_seconds=0.0,
            command=_fake_install(_TRANSIENT_OUTPUT, exit_code=1, succeed_after=1),
            sleep=self.slept.append,
        )

        self.assertEqual(code, 0)
        self.assertEqual(self._attempts(), 2, "the second attempt should succeed")
        self.assertEqual(len(self.slept), 1, "one wait between two attempts")

    def test_a_genuine_failure_is_not_retried(self):
        """The branch that would turn a real break into a timeout."""
        code = tool.run_pip_install(
            ["-e", ".[nonexistent]"],
            attempts=3,
            delay_seconds=0.0,
            command=_fake_install(_GENUINE_OUTPUT, exit_code=1, succeed_after=99),
            sleep=self.slept.append,
        )

        self.assertEqual(code, 1)
        self.assertEqual(self._attempts(), 1, "a resolution error must fail fast")
        self.assertEqual(self.slept, [])

    def test_a_cut_fetch_on_every_attempt_still_fails(self):
        code = tool.run_pip_install(
            ["-e", "."],
            attempts=3,
            delay_seconds=0.0,
            command=_fake_install(_TRANSIENT_OUTPUT, exit_code=2, succeed_after=99),
            sleep=self.slept.append,
        )

        self.assertEqual(code, 2, "the last attempt's exit code is the result")
        self.assertEqual(self._attempts(), 3)
        self.assertEqual(len(self.slept), 2)


class WorkflowWiringTest(unittest.TestCase):
    """Every install the workflows run goes through the tool.

    Without this, the tool keeps passing its own tests while CI quietly stops
    calling it -- the failure mode `tools/README.md` calls the difference
    between CI-wired and merely present.
    """

    WORKFLOWS = (
        _REPO_ROOT / ".github" / "workflows" / "ci.yml",
        _REPO_ROOT / ".github" / "workflows" / "pages.yml",
    )

    def test_no_workflow_installs_without_the_retry(self):
        offenders: list[str] = []
        for workflow in self.WORKFLOWS:
            for number, line in enumerate(
                workflow.read_text(encoding="utf-8").splitlines(), start=1
            ):
                stripped = line.strip()
                if not stripped.startswith("python -m pip install"):
                    continue
                # Upgrading pip itself is one small wheel from the same host;
                # it is left alone so the retry cannot mask a broken pip.
                if stripped.endswith("--upgrade pip"):
                    continue
                offenders.append(f"{workflow.name}:{number}: {stripped}")

        self.assertEqual(
            [],
            offenders,
            "these installs bypass tools/pip_install_retry.py",
        )

    def test_the_tool_is_actually_invoked(self):
        """The mirror of the check above: present, not just not-bypassed."""
        for workflow in self.WORKFLOWS:
            with self.subTest(workflow=workflow.name):
                self.assertIn(
                    "tools/pip_install_retry.py",
                    workflow.read_text(encoding="utf-8"),
                )


if __name__ == "__main__":
    unittest.main()
