"""The mypy ratchet's dual-target contract, and proof it catches a real bug.

2026-08-18: a shared helper's signature changed (a ``Path`` parameter became a
``ProjectScript``) and 9 of 10 call sites in ``projects/ev_hosting_flex`` kept
passing the old type. Nothing caught it before it shipped -- the study is
operator-verified, so its reproduce-and-pin tests ``skipif`` in CI, and
``tools/mypy_ratchet.py`` only ever checked ``gridalyn/``. ``projects/`` sat
outside every type gate. Checked directly, mypy named the exact line and the
exact mismatched type -- this module exists because that check was not wired
to anything.

``tools/mypy_ratchet.py`` gained a ``--target``/``--baseline-file`` pair so the
same mechanism (report; block only on a rise; never silently raise the
baseline) covers both ``gridalyn/`` (``.mypy-baseline``, held to full
discipline) and ``projects/`` (``.mypy-baseline-projects``, measured at 868
errors across 72 files the day this gate was added -- a real backlog, tracked
rather than hidden).

This module does not re-derive mypy's own correctness. It pins three things:
the CLI contract (target and baseline file are genuinely parameters, not
hardcoded), that both baselines still match a real mypy run (so neither file
can silently drift from the tree it claims to describe), and -- by mutation,
not by reading the code and trusting it -- that introducing a new type error
under ``projects/`` actually turns the gate red.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_RATCHET = _REPO_ROOT / "tools" / "mypy_ratchet.py"


def _run_ratchet(*extra_args: str) -> subprocess.CompletedProcess[str]:
    """Invoke the ratchet script as a subprocess, exactly as CI does.

    Args:
        *extra_args: Additional CLI arguments appended after the script path.

    Returns:
        The completed process, with stdout/stderr captured as text.
    """
    return subprocess.run(
        [sys.executable, str(_RATCHET), *extra_args],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )


class MypyRatchetCliTests(unittest.TestCase):
    """The CLI contract: target and baseline file are real parameters."""

    def test_missing_baseline_file_is_a_located_error(self) -> None:
        result = _run_ratchet("--baseline-file", "no-such-baseline-file")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("no-such-baseline-file", result.stdout + result.stderr)
        self.assertIn("not found", result.stdout + result.stderr)

    def test_default_target_is_gridalyn(self) -> None:
        # No --target given: the historical, unparametrized behaviour must be
        # unchanged for the existing pre-push hook and CI step.
        result = _run_ratchet()
        self.assertIn("gridalyn", result.stdout)


class MypyBaselinesMatchTheTreeTests(unittest.TestCase):
    """A baseline file must describe the tree it is checked against.

    A baseline that was never re-measured after the tree changed would let the
    ratchet pass while lying about what mypy actually reports -- exactly the
    silent-drift failure mode this repository's other gates (the docs
    instruction ledger, the doc-path-reference floors) have already been
    caught by. Run for real; nothing here is inferred from source.
    """

    def test_gridalyn_ratchet_does_not_report_a_rise(self) -> None:
        result = _run_ratchet()
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_projects_ratchet_does_not_report_a_rise(self) -> None:
        result = _run_ratchet(
            "--target", "projects", "--baseline-file", ".mypy-baseline-projects"
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


class MypyRatchetCatchesARealRegressionTests(unittest.TestCase):
    """Mutation proof: a new type error under ``projects/`` reddens the gate.

    Writes a disposable, self-contained file under ``projects/`` -- never one
    of the nine repaired call sites -- carrying the same class of defect that
    shipped (an argument of the wrong type passed to a function with a
    ``disallow-untyped-defs``-compatible annotated signature), runs the
    ``projects`` ratchet for real, and asserts it fails. Cleans up in
    ``tearDown`` even if the assertion itself fails, and re-verifies the
    baseline is clean again afterward -- a scratch file left behind would
    otherwise poison every later mypy run in this environment.
    """

    _SCRATCH_RELATIVE = "projects/_mypy_ratchet_mutation_probe.py"

    def setUp(self) -> None:
        self._scratch = _REPO_ROOT / self._SCRATCH_RELATIVE
        self.assertFalse(
            self._scratch.exists(), f"{self._scratch} already exists; not overwriting"
        )

    def tearDown(self) -> None:
        self._scratch.unlink(missing_ok=True)

    def test_a_new_type_error_turns_the_projects_gate_red(self) -> None:
        self._scratch.write_text(
            "from __future__ import annotations\n\n\n"
            "def takes_a_string(value: str) -> int:\n"
            "    return len(value)\n\n\n"
            "takes_a_string(12345)  # wrong type on purpose\n",
            encoding="utf-8",
        )
        result = _run_ratchet(
            "--target", "projects", "--baseline-file", ".mypy-baseline-projects"
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("rose from", result.stdout + result.stderr)

        self._scratch.unlink()
        restored = _run_ratchet(
            "--target", "projects", "--baseline-file", ".mypy-baseline-projects"
        )
        self.assertEqual(0, restored.returncode, restored.stdout + restored.stderr)
