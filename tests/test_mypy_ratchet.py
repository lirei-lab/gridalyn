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

import re
import subprocess
import sys
import unittest
import warnings
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


_REPORT = re.compile(
    r"^mypy \((?P<target>[^)]+)\): (?P<count>\d+) errors \(baseline (?P<baseline>\d+)\)"
)


#: Every ratchet CI runs, as ``(name, extra CLI args)``.
#:
#: Declared once and iterated, rather than one helper per target. The slack
#: check below covered ``projects`` alone while three ratchets were wired, and
#: the uncovered ones were where the slack actually was: ``.mypy-baseline-twin``
#: recorded 21 against a measured 12 for weeks, over the layer that was being
#: edited most. A per-target helper is how that asymmetry survived.
RATCHET_TARGETS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("gridalyn", ()),
    (
        "projects",
        ("--target", "projects", "--baseline-file", ".mypy-baseline-projects"),
    ),
    (
        "gridalyn/twin",
        ("--target", "gridalyn/twin", "--baseline-file", ".mypy-baseline-twin"),
    ),
)


def _error_count(*args: str) -> tuple[int, int]:
    """Return ``(baseline, measured)`` error counts for one ratchet target.

    Parsed from the ratchet's own report line rather than re-running mypy here,
    so the numbers are the ones the gate itself acts on.

    Args:
        *args: The target's CLI arguments, from :data:`RATCHET_TARGETS`.

    Returns:
        The baseline the ratchet read, and the count mypy reported for this
        tree in this environment. They are equal on a machine whose baseline
        was measured against the same installed set, and differ where it was
        not -- which is the case this test suite must not assume away.

    Raises:
        AssertionError: If the ratchet printed no recognisable report line,
            which means it crashed rather than measured.
    """
    result = _run_ratchet(*args)
    match = _REPORT.search(result.stdout)
    assert match is not None, (
        "the ratchet printed no report line, so nothing can be measured from "
        f"it:\n{result.stdout}{result.stderr}"
    )
    return int(match.group("baseline")), int(match.group("count"))


def _projects_error_count() -> tuple[int, int]:
    """Return ``(baseline, measured)`` for ``projects``, for the mutation test."""
    return _error_count(
        "--target", "projects", "--baseline-file", ".mypy-baseline-projects"
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

    def test_every_baseline_slack_is_reported_not_hidden(self) -> None:
        """Record how far each baseline sits above what mypy actually reports.

        ``test_projects_ratchet_does_not_report_a_rise`` passes on any count at
        or below the baseline, so a baseline measured on one machine and run on
        another can sit well above the tree without any gate noticing -- and a
        baseline above the tree is slack the ratchet will absorb a real
        regression into. This does not fail on slack, because whether to
        re-measure is a human decision; it names the number so the decision is
        made against evidence rather than rediscovered from a mute failure.

        Covers every entry in :data:`RATCHET_TARGETS`. It previously covered
        ``projects`` only, which is how ``.mypy-baseline-twin`` came to record
        21 against a measured 12 -- nine errors of headroom on the layer under
        the most change, reported by the tool on every run and by no gate.
        """
        for name, args in RATCHET_TARGETS:
            with self.subTest(target=name):
                baseline, measured = _error_count(*args)
                self.assertLessEqual(
                    measured,
                    baseline,
                    f"{name} ratchet reports a rise: {measured} > "
                    f"baseline {baseline}",
                )
                if measured < baseline:
                    # A warning, not a print: CI runs `pytest -q` without `-s`,
                    # which swallows stdout from a passing test but still
                    # renders the warnings summary. A finding nobody can see is
                    # not reported.
                    warnings.warn(
                        f"{name} baseline slack: mypy reports {measured}, "
                        f"baseline records {baseline} "
                        f"({baseline - measured} absorbed). The ratchet would "
                        "let a regression of that size through here. "
                        "Re-measure the baseline in the environment CI uses.",
                        stacklevel=2,
                    )

    def test_every_wired_ratchet_is_covered_by_the_slack_check(self) -> None:
        """The declared target list must match what CI actually runs.

        A ratchet added to the workflow and not to :data:`RATCHET_TARGETS`
        would silently escape the slack check -- exactly how the twin baseline
        went unwatched.
        """
        workflow = (_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
        wired = set(re.findall(r"--baseline-file (\S+)", workflow))
        declared = {
            args[args.index("--baseline-file") + 1]
            for _, args in RATCHET_TARGETS
            if "--baseline-file" in args
        }
        self.assertEqual(
            wired,
            declared,
            "CI runs a ratchet this test does not check (or vice versa); add it "
            "to RATCHET_TARGETS so its slack is measured",
        )


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
        # Measure the slack BEFORE mutating, rather than assuming the tree sits
        # exactly at its baseline. It does on the machine the baseline was
        # measured on, and this test injected a single error on that
        # assumption -- so in any environment reporting FEWER errors than the
        # baseline records, that one error was absorbed by the slack, the gate
        # stayed green, and the assertion failed with a bare `0 == 0` naming
        # neither number. CI has been red on exactly that since the projects
        # ratchet was added (2026-08-19). The slack is a real finding about the
        # baseline, reported below; it is not this test's subject, and a
        # mutation proof must not depend on it being zero.
        baseline, before = _projects_error_count()
        slack = baseline - before
        self.assertGreaterEqual(
            slack,
            0,
            f"projects ratchet already reports a rise ({before} > {baseline}) "
            "before this test mutated anything",
        )

        # One error more than the slack can absorb, so the gate must redden in
        # any environment. Each line is the defect class that shipped: an
        # argument of the wrong type into an annotated signature.
        errors = slack + 1
        calls = "".join(
            f"takes_a_string({n})  # wrong type on purpose\n" for n in range(errors)
        )
        self._scratch.write_text(
            "from __future__ import annotations\n\n\n"
            "def takes_a_string(value: str) -> int:\n"
            "    return len(value)\n\n\n" + calls,
            encoding="utf-8",
        )
        result = _run_ratchet(
            "--target", "projects", "--baseline-file", ".mypy-baseline-projects"
        )
        detail = (
            f"injected {errors} type error(s) into {self._SCRATCH_RELATIVE} "
            f"(measured {before} errors against baseline {baseline}, "
            f"slack {slack}); the ratchet should have reported a rise.\n"
            f"{result.stdout}{result.stderr}"
        )
        self.assertNotEqual(0, result.returncode, detail)
        self.assertIn("rose from", result.stdout + result.stderr, detail)

        self._scratch.unlink()
        restored = _run_ratchet(
            "--target", "projects", "--baseline-file", ".mypy-baseline-projects"
        )
        self.assertEqual(0, restored.returncode, restored.stdout + restored.stderr)
