#!/usr/bin/env python3
"""Check a study's stated headline figures against its pinned baseline.

CLAUDE.md designates each study's CALIBRATION.md as the source of truth and
tells readers to consult it before quoting a metric. That instruction is only
safe while the file agrees with `baselines/results_baseline.json`, and nothing
enforced that: a re-base moves the pins, the prose is appended to rather than
revised, and the stated figure quietly stops being true. It has happened --
`ev_hosting_flex` carried a firm P50 of 4 against a pinned 11.

Free prose cannot be checked, and historical sections legitimately record
superseded numbers. So this gate reads only ONE table, the study's "Current
headline figures", where each row names the baseline pin it mirrors:

    | Figure | Current value | Baseline pin |
    |---|---|---|
    | Firm hosting capacity, P50 | 11 EVs | `cred.firm_p50` |

Comparison is at the precision the table displays: a row showing `480.06` is
checked against `round(expected, 2)`, so the document may round for legibility
but cannot round a stale number into looking current.

Usage:
    python tools/check_calibration_claims.py                 # report
    python tools/check_calibration_claims.py --check         # non-zero on drift
    python tools/check_calibration_claims.py --study NAME    # one study
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PROJECTS = REPO_ROOT / "projects"

#: The heading whose table is gated. Everything else in the file is prose the
#: gate deliberately does not read.
CLAIMS_HEADING = "Current headline figures"

_ROW = re.compile(r"^\|(?P<cells>.+)\|\s*$")
_PIN = re.compile(r"`([A-Za-z0-9_.]+)`")
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


class ClaimError(Exception):
    """A study's claims table could not be read."""


def _decimals(text: str) -> int:
    """Return how many decimal places a rendered number shows.

    Args:
        text: The numeric substring as the document renders it.

    Returns:
        The count of digits after the decimal point, zero when there is none.
    """
    return -Decimal(text).as_tuple().exponent if "." in text else 0


def _parse_row(line: str, path: Path) -> tuple[str, str, float, int] | None:
    """Return one claim from a table row, or None when the row is not a claim.

    Args:
        line: A single line of the document.
        path: The document, named in any error.

    Returns:
        ``(figure, pin_id, value, decimals)``, or None for separators, headers
        and non-table lines.

    Raises:
        ClaimError: If a claim row does not carry exactly one pin and a number.
    """
    match = _ROW.match(line.strip())
    if not match:
        return None
    cells = [cell.strip() for cell in match.group("cells").split("|")]
    if len(cells) < 3 or set(cells[0]) <= {"-", ":", " "}:
        return None
    if cells[0].lower() in {"figure", "claim"}:
        return None
    pins = _PIN.findall(cells[-1])
    numbers = _NUMBER.findall(cells[1])
    if len(pins) != 1 or not numbers:
        raise ClaimError(
            f"{path}: row {cells[0]!r} must give one value and name exactly "
            f"one pin in backticks; found {len(numbers)} number(s) and "
            f"{len(pins)} pin(s)"
        )
    return (cells[0], pins[0], float(numbers[0]), _decimals(numbers[0]))


def read_claims(path: Path) -> list[tuple[str, str, float, int]]:
    """Parse the claims table out of a CALIBRATION document.

    Args:
        path: The CALIBRATION.md to read.

    Returns:
        ``(figure, pin_id, value, decimals)`` for each declared claim.

    Raises:
        ClaimError: If the heading is missing, or a row under it does not name
            exactly one pin and one number; the message names the row.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.startswith("#") and CLAIMS_HEADING.lower() in line.lower():
            start = index + 1
            break
    if start is None:
        raise ClaimError(
            f"{path}: no {CLAIMS_HEADING!r} heading. Every gated study needs one "
            "table of the figures it presents as current, each row naming the "
            "baseline pin it mirrors."
        )

    claims: list[tuple[str, str, float, int]] = []
    for line in lines[start:]:
        if line.startswith("#"):
            break
        claim = _parse_row(line, path)
        if claim is not None:
            claims.append(claim)
    if not claims:
        raise ClaimError(f"{path}: the {CLAIMS_HEADING!r} table has no rows")
    return claims


def read_pins(path: Path) -> dict[str, float | None]:
    """Return the pinned expected values, keyed by metric id.

    Args:
        path: The ``results_baseline.json`` to read.

    Returns:
        Metric id -> expected value.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {metric["id"]: metric["expected"] for metric in payload["metrics"]}


def check_study(name: str) -> list[str]:
    """Compare one study's claims table against its baseline.

    Args:
        name: Directory name of the study under ``projects/``.

    Returns:
        Failure strings, empty when every claim matches.

    Raises:
        ClaimError: If either file is missing or the table is malformed.
    """
    root = PROJECTS / name
    doc = root / "CALIBRATION.md"
    pins_path = root / "baselines" / "results_baseline.json"
    for path in (doc, pins_path):
        if not path.is_file():
            raise ClaimError(f"{path} not found")

    pins = read_pins(pins_path)
    failures: list[str] = []
    for figure, pin, stated, places in read_claims(doc):
        if pin not in pins:
            failures.append(
                f"{figure}: names pin {pin!r}, which the baseline does not "
                f"carry (known: {len(pins)} pins)"
            )
            continue
        expected = pins[pin]
        if expected is None:
            failures.append(f"{figure}: pin {pin!r} is null in the baseline")
            continue
        if round(float(expected), places) != stated:
            failures.append(
                f"{figure}: document states {stated} but pin {pin} is "
                f"{expected} (rounded to {places} dp: "
                f"{round(float(expected), places)})"
            )
    return failures


def gated_studies() -> list[str]:
    """Return every study whose CALIBRATION.md declares a claims table.

    Returns:
        Sorted study directory names.
    """
    found = []
    for doc in sorted(PROJECTS.glob("*/CALIBRATION.md")):
        if CLAIMS_HEADING.lower() in doc.read_text(encoding="utf-8").lower():
            found.append(doc.parent.name)
    return found


def main(argv: list[str] | None = None) -> int:
    """Run the claims gate.

    Args:
        argv: Command-line arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        The process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--study", help="check only this study")
    parser.add_argument(
        "--check", action="store_true", help="exit non-zero on any drift"
    )
    args = parser.parse_args(argv)

    studies = [args.study] if args.study else gated_studies()
    if not studies:
        print("no study declares a claims table; nothing to gate")
        return 0

    total = 0
    for name in studies:
        failures = check_study(name)
        claims = read_claims(PROJECTS / name / "CALIBRATION.md")
        total += len(failures)
        status = "OK" if not failures else f"{len(failures)} DRIFTED"
        print(f"{name}: {len(claims)} claim(s) gated -- {status}")
        for failure in failures:
            print(f"  {failure}")
    if total and args.check:
        print(
            "\nFAIL: CALIBRATION.md states a figure its own baseline refutes. "
            "Either the document is stale after a re-base, or the re-base was "
            "not deliberate. Fix the document, never the pin, unless the pin "
            "move was intended and recorded.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
