#!/usr/bin/env python3
"""Run mypy over ``gridalyn/`` and fail only if the error count rose.

Why a ratchet rather than a pass/fail gate: the tree carries a real backlog of
type errors, and mypy follows imports. Checking a single edited file drags in
its whole import closure, so a plain gate fails on debt the author did not
write -- 21 errors across 10 files for one clean file, measured. A gate that
fires on someone else's code is a gate people learn to bypass.

The baseline lives in ``.mypy-baseline`` so this script and the CI job read the
same number from the same place. It is meaningful only alongside the
environment it was measured in: mypy's reading depends on which third-party
stubs resolve, and the same tree reports 145 with the project installed and
roughly 126 in an isolated env that cannot see them. Run this against a
``pip install -e ".[dev]"`` environment, which is what CI uses.

Exit codes:
    0: count is at or below the baseline.
    1: count rose, or mypy produced no summary line (it most likely crashed,
       and "no errors printed" must never be read as "clean").
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BASELINE_FILE = _REPO_ROOT / ".mypy-baseline"
_TARGET = "gridalyn"
_ARGS = ["--ignore-missing-imports", "--disallow-untyped-defs"]
_FOUND = re.compile(r"^Found (\d+) errors? in ", re.MULTILINE)
_CLEAN = re.compile(r"^Success: no issues found", re.MULTILINE)


def read_baseline() -> int:
    """Return the pinned error count.

    Returns:
        The integer recorded in ``.mypy-baseline``.

    Raises:
        SystemExit: If the file is missing or does not hold a single integer.
    """
    if not _BASELINE_FILE.is_file():
        raise SystemExit(
            f"{_BASELINE_FILE} not found; it is the single source for the mypy "
            "baseline and both this hook and the CI typecheck job read it"
        )
    text = _BASELINE_FILE.read_text().strip()
    if not text.isdigit():
        raise SystemExit(f"{_BASELINE_FILE} must hold a single integer, found {text!r}")
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


def run_mypy() -> tuple[int, str]:
    """Run mypy and return its error count alongside the raw output.

    Returns:
        A ``(count, output)`` pair.

    Raises:
        SystemExit: If mypy printed no recognisable summary line.
    """
    proc = subprocess.run(
        [resolve_interpreter(), "-m", "mypy", *_ARGS, _TARGET],
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
    """Compare the current count against the baseline.

    Returns:
        Process exit code.
    """
    baseline = read_baseline()
    count, output = run_mypy()
    if count > baseline:
        sys.stderr.write(output)
        sys.stderr.write(
            f"\nmypy error count rose from {baseline} to {count}.\n"
            "Fix the new type errors listed above. Do not raise the number in "
            ".mypy-baseline to go green.\n"
        )
        return 1
    if count < baseline:
        print(
            f"mypy: {count} errors (baseline {baseline}). Lower "
            f".mypy-baseline to {count} to lock the improvement in."
        )
        return 0
    print(f"mypy: {count} errors (baseline {baseline}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
