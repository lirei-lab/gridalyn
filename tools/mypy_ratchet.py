#!/usr/bin/env python3
"""Run mypy over a target and fail only if its error count rose.

Why a ratchet rather than a pass/fail gate: a tree with a real backlog of type
errors, and mypy follows imports, so checking a single edited file drags in
its whole import closure -- a plain gate fails on debt the author did not
write, 21 errors across 10 files for one clean file, measured. A gate that
fires on someone else's code is a gate people learn to bypass.

Two independent targets, two independent baselines
----------------------------------------------------
``gridalyn/`` (``.mypy-baseline``) and ``projects/`` (``.mypy-baseline-projects``,
added 2026-08-18) are ratcheted separately, on purpose. Measured the day the
second target was added: 0 errors in ``gridalyn/`` under this configuration
(the SDK is held to full type discipline) against 868 in ``projects/`` across
72 files -- study scripts were never held to the same bar. Folding the two
into one baseline would either fail immediately (0 does not cover 868) or
require accepting 868 as the shared number, which blesses the entire backlog
as fine rather than stopping it from growing. Same mechanism, honest separate
numbers.

Why this is the gate that would have caught a real bug this one number missed
-------------------------------------------------------------------------------
2026-08-18: a shared helper's signature changed (``Path`` parameter ->
``ProjectScript``) and 9 of 10 call sites in ``projects/ev_hosting_flex``
kept passing the old type. No test caught it -- the study is
operator-verified, so its reproduce-and-pin tests skip in CI -- and it shipped
for one commit before an operator hit it running the study directly. Measured
against the reintroduced bug: mypy named the exact line and the exact
mismatched type (``Argument 2 ... has incompatible type "Path"; expected
"ProjectScript"``). An import-only smoke test does not catch this class of
defect -- the failure is inside a call, not at import time -- which is why
this ratchet, not a lighter check, is the one being extended to ``projects/``.

The baseline file is the single source both this script and CI read, so the
two cannot disagree. It is meaningful only alongside the environment it was
measured in: mypy's reading depends on which third-party stubs resolve, and
the same tree reports a different count in an isolated env that cannot see
them. Run this against a ``pip install -e ".[dev]"`` environment, which is
what CI uses.

Exit codes:
    0: count is at or below the baseline.
    1: count rose, or mypy produced no summary line (it most likely crashed,
       and "no errors printed" must never be read as "clean").
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ARGS = ["--ignore-missing-imports", "--disallow-untyped-defs"]
_FOUND = re.compile(r"^Found (\d+) errors? in ", re.MULTILINE)
_CLEAN = re.compile(r"^Success: no issues found", re.MULTILINE)


def read_baseline(baseline_file: Path) -> int:
    """Return the pinned error count.

    Args:
        baseline_file: The single-integer file to read.

    Returns:
        The integer recorded in ``baseline_file``.

    Raises:
        SystemExit: If the file is missing or does not hold a single integer.
    """
    if not baseline_file.is_file():
        raise SystemExit(
            f"{baseline_file} not found; it is the single source for the mypy "
            "baseline and both this hook and the CI typecheck job read it"
        )
    text = baseline_file.read_text().strip()
    if not text.isdigit():
        raise SystemExit(f"{baseline_file} must hold a single integer, found {text!r}")
    return int(text)


def resolve_interpreter() -> str:
    """Return the interpreter that has the project and mypy installed.

    This script is deliberately stdlib-only so any ``python3`` can bootstrap it
    -- a git hook inherits whatever PATH the shell had, which on some machines
    has no ``python`` at all. What mypy actually needs is the *project*
    environment, because the baseline count depends on which third-party stubs
    resolve. Prefers the repo's ``.venv``, falls back to the running
    interpreter.

    Returns:
        Path to a usable interpreter.

    Raises:
        SystemExit: If no candidate can import mypy, naming the fix.
    """
    candidates = [_REPO_ROOT / ".venv" / "bin" / "python", Path(sys.executable)]
    for candidate in candidates:
        if not candidate.exists():
            continue
        probe = subprocess.run(
            [str(candidate), "-c", "import mypy"],
            capture_output=True,
            check=False,
        )
        if probe.returncode == 0:
            return str(candidate)
    tried = ", ".join(str(c) for c in candidates)
    raise SystemExit(
        f"mypy is not importable by any candidate interpreter (tried: {tried}).\n"
        'Install it with: pip install -e ".[typing]"  (or ".[dev]")'
    )


def run_mypy(target: str) -> tuple[int, str]:
    """Run mypy over ``target`` and return its error count with the raw output.

    Args:
        target: Path (relative to the repo root) mypy checks.

    Returns:
        A ``(count, output)`` pair.

    Raises:
        SystemExit: If mypy printed no recognisable summary line.
    """
    proc = subprocess.run(
        [resolve_interpreter(), "-m", "mypy", *_ARGS, target],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    output = proc.stdout + proc.stderr
    if _CLEAN.search(output):
        return 0, output
    match = _FOUND.search(output)
    if match is None:
        sys.stderr.write(output)
        raise SystemExit(
            "mypy produced no recognisable summary line -- it most likely "
            "crashed. Refusing to report this as a pass."
        )
    return int(match.group(1)), output


def main() -> int:
    """Compare the current count against the baseline for one target.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        default="gridalyn",
        help="Path (relative to the repo root) mypy checks. Default: gridalyn",
    )
    parser.add_argument(
        "--baseline-file",
        default=".mypy-baseline",
        help="Path (relative to the repo root) holding the pinned error count. "
        "Default: .mypy-baseline",
    )
    args = parser.parse_args()
    baseline_file = _REPO_ROOT / args.baseline_file

    baseline = read_baseline(baseline_file)
    count, output = run_mypy(args.target)
    if count > baseline:
        sys.stderr.write(output)
        sys.stderr.write(
            f"\nmypy error count for {args.target!r} rose from {baseline} to "
            f"{count}.\nFix the new type errors listed above. Do not raise the "
            f"number in {args.baseline_file} to go green.\n"
        )
        return 1
    if count < baseline:
        print(
            f"mypy ({args.target}): {count} errors (baseline {baseline}). "
            f"Lower {args.baseline_file} to {count} to lock the improvement in."
        )
        return 0
    print(f"mypy ({args.target}): {count} errors (baseline {baseline}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
