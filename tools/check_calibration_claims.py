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

#: The heading whose table is gated against the pinned baseline. Everything
#: else in the file is prose the gate deliberately does not read.
CLAIMS_HEADING = "Current headline figures"

#: The heading whose table is gated against the study's DECLARED knobs.
#:
#: A second source of truth, and a second way the same defect struck. The
#: "Recommended values" table recommended lowering the EV coincident draw and
#: the sweep; `10-03` adopted every recommendation; the table kept displaying
#: the pre-adoption numbers in a column headed "Current" and an "Action" column
#: telling a reader to do work already done. A researcher reading it saw a
#: model over-stated by ~70% on EV power and ~186% on session energy.
#:
#: Headline figures are checked against ``results_baseline.json``; knobs are
#: checked against ``project.yaml``'s ``spec.inputs.studyConfig``, which is the
#: declarative source ``scripts/config.py`` itself reads.
KNOBS_HEADING = "Current knob values"

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


def _parse_row(
    line: str,
    path: Path,
    *,
    multiple_refs: bool = False,
) -> tuple[str, tuple[str, ...], float, int] | None:
    """Return one claim from a table row, or None when the row is not a claim.

    Args:
        line: A single line of the document.
        path: The document, named in any error.
        multiple_refs: Whether the last cell may name more than one reference.
            The knobs table allows it, so a DERIVED figure can be gated as the
            product of the knobs it is computed from -- the EV coincident draw
            is ``evUnitKw x diversityFactor``, and gating only the two factors
            would leave the product free to go stale beside them.

    Returns:
        ``(figure, refs, value, decimals)``, or None for separators, headers
        and non-table lines.

    Raises:
        ClaimError: If a claim row does not carry a number and the expected
            number of references.
    """
    match = _ROW.match(line.strip())
    if not match:
        return None
    cells = [cell.strip() for cell in match.group("cells").split("|")]
    if len(cells) < 3 or set(cells[0]) <= {"-", ":", " "}:
        return None
    if cells[0].lower() in {"figure", "claim", "knob"}:
        return None
    refs = _PIN.findall(cells[-1])
    numbers = _NUMBER.findall(cells[1])
    wanted = "at least one" if multiple_refs else "exactly one"
    if not refs or (len(refs) != 1 and not multiple_refs) or not numbers:
        raise ClaimError(
            f"{path}: row {cells[0]!r} must give one value and name {wanted} "
            f"reference in backticks; found {len(numbers)} number(s) and "
            f"{len(refs)} reference(s)"
        )
    return (cells[0], tuple(refs), float(numbers[0]), _decimals(numbers[0]))


def read_table(
    path: Path,
    heading: str,
    *,
    multiple_refs: bool = False,
    required: bool = True,
) -> list[tuple[str, tuple[str, ...], float, int]]:
    """Parse one gated table out of a CALIBRATION document.

    Args:
        path: The CALIBRATION.md to read.
        heading: Heading text whose table is read. Everything under the next
            heading is prose the gate does not touch.
        multiple_refs: Whether a row may name more than one reference.
        required: Whether a missing heading is an error. The knobs table is
            optional, so a study can adopt the pins gate without being forced
            to declare knobs in the same change.

    Returns:
        ``(figure, refs, value, decimals)`` for each declared row, empty when
        an optional heading is absent.

    Raises:
        ClaimError: If a required heading is missing, or a row under it is
            malformed; the message names the row.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.startswith("#") and heading.lower() in line.lower():
            start = index + 1
            break
    if start is None:
        if not required:
            return []
        raise ClaimError(
            f"{path}: no {heading!r} heading. Every gated study needs one "
            "table of the figures it presents as current, each row naming the "
            "baseline pin it mirrors."
        )

    rows: list[tuple[str, tuple[str, ...], float, int]] = []
    for line in lines[start:]:
        if line.startswith("#"):
            break
        row = _parse_row(line, path, multiple_refs=multiple_refs)
        if row is not None:
            rows.append(row)
    if not rows:
        raise ClaimError(f"{path}: the {heading!r} table has no rows")
    return rows


def read_claims(path: Path) -> list[tuple[str, tuple[str, ...], float, int]]:
    """Parse the headline-figures table, each row naming one baseline pin."""
    return read_table(path, CLAIMS_HEADING)


def read_knobs(path: Path) -> list[tuple[str, tuple[str, ...], float, int]]:
    """Parse the knob table, each row naming one or more declared knobs."""
    return read_table(path, KNOBS_HEADING, multiple_refs=True, required=False)


def read_pins(path: Path) -> dict[str, float | None]:
    """Return the pinned expected values, keyed by metric id.

    Args:
        path: The ``results_baseline.json`` to read.

    Returns:
        Metric id -> expected value.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {metric["id"]: metric["expected"] for metric in payload["metrics"]}


def read_declared_knobs(path: Path) -> dict[str, float]:
    """Return the study's declared scalar knobs, keyed by ``studyConfig`` name.

    Read from ``project.yaml`` rather than by importing ``scripts/config.py``:
    the YAML block is the declarative source that module itself reads, and
    importing a study's config would execute it -- which resolves paths, loads
    a grid config and can fail for reasons that have nothing to do with a
    stale document.

    Args:
        path: The study's ``project.yaml``.

    Returns:
        Knob name -> value, for scalar knobs only. Lists and mappings are
        skipped: a document should point at them rather than restate them,
        because a restated sequence is exactly what went stale.

    Raises:
        ClaimError: If the file declares no ``spec.inputs.studyConfig`` block.
    """
    import yaml

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    config = ((raw.get("spec") or {}).get("inputs") or {}).get("studyConfig")
    if not isinstance(config, dict):
        raise ClaimError(
            f"{path}: spec.inputs.studyConfig not found or not a mapping; a "
            f"study that declares a {KNOBS_HEADING!r} table must declare its "
            "knobs there"
        )
    return {
        key: float(value)
        for key, value in config.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }


def check_study_knobs(name: str) -> list[str]:
    """Compare one study's knob table against its declared study config.

    Args:
        name: Directory name of the study under ``projects/``.

    Returns:
        Failure strings, empty when every knob matches or none is declared.

    Raises:
        ClaimError: If the study declares a knob table it cannot resolve.
    """
    root = PROJECTS / name
    doc = root / "CALIBRATION.md"
    rows = read_knobs(doc)
    if not rows:
        return []
    declared = read_declared_knobs(root / "project.yaml")

    failures: list[str] = []
    for knob, refs, stated, places in rows:
        missing = [ref for ref in refs if ref not in declared]
        if missing:
            failures.append(
                f"{knob}: names knob(s) {', '.join(missing)}, which "
                f"spec.inputs.studyConfig does not declare as a scalar "
                f"(declared scalars: {len(declared)})"
            )
            continue
        expected = 1.0
        for ref in refs:
            expected *= declared[ref]
        if round(expected, places) != stated:
            shown = " x ".join(f"{ref}={declared[ref]}" for ref in refs)
            failures.append(
                f"{knob}: document states {stated} but {shown} gives "
                f"{expected} (rounded to {places} dp: {round(expected, places)})"
            )
    return failures


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
    for figure, refs, stated, places in read_claims(doc):
        (pin,) = refs
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
        doc = PROJECTS / name / "CALIBRATION.md"
        failures = check_study(name) + check_study_knobs(name)
        gated = len(read_claims(doc)) + len(read_knobs(doc))
        total += len(failures)
        status = "OK" if not failures else f"{len(failures)} DRIFTED"
        print(f"{name}: {gated} claim(s) gated -- {status}")
        for failure in failures:
            print(f"  {failure}")
    if total and args.check:
        print(
            "\nFAIL: CALIBRATION.md states a figure its own source refutes -- "
            "the pinned baseline for a headline, or the declared studyConfig "
            "for a knob. Either the document is stale after a re-base, or the "
            "re-base was not deliberate. Fix the document, never the pin or "
            "the knob, unless that move was intended and recorded.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
