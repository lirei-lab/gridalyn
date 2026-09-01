#!/usr/bin/env python3
"""Report how far the SDK's public verbs have drifted from the documented table.

``docs/contributing/conventions.md`` tells contributors to "pick the prefix
that matches the behavior rather than inventing a new one". That instruction is
only worth following while the table describes the API: a guide that forbids
verbs the SDK already uses is one contributors learn to ignore.

This tool reads the prefixes out of that document -- it does not keep a second
copy -- AST-scans every public module-level function under ``gridalyn/`` and
reports the compliance rate. With ``--check`` it fails when an undocumented
prefix has become established, which is the signal that either the code should
use an existing verb or the table should grow one.

Usage:
    python tools/verb_prefixes.py            # report
    python tools/verb_prefixes.py --check    # fail on established drift
"""

from __future__ import annotations

import argparse
import ast
import collections
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONVENTIONS = REPO_ROOT / "docs" / "contributing" / "conventions.md"
PACKAGE = REPO_ROOT / "gridalyn"

#: An undocumented prefix at or above this many public functions is no longer an
#: accident; it is a verb the SDK uses and the table does not acknowledge.
ESTABLISHED = 3

#: Names that are not helpers and carry no verb contract. ``main`` is a CLI
#: entry point and ``parse_args`` is its argparse companion, repeated once per
#: CLI module by argparse's own shape.
ENTRY_POINT_NAMES = frozenset({"main", "parse_args"})

_TABLE_ROW = re.compile(r"^\|\s*(`[^|]+`)\s*\|")
_PREFIX = re.compile(r"`(\w+)_\*`")


def read_documented_prefixes(
    path: Path = CONVENTIONS,
) -> tuple[set[str], set[str], set[str]]:
    """Extract the three prefix sets the guide declares.

    Args:
        path: The conventions document to parse.

    Returns:
        A ``(documented, acknowledged, unwanted)`` triple of prefix sets,
        each without the trailing underscore. ``documented`` verbs count toward
        compliance; ``acknowledged`` prefixes are entry points and noun-prefixed
        families, which are neither compliant nor drift; ``unwanted`` verbs are
        named as discouraged, so they are reported but are not fresh drift.

    Raises:
        FileNotFoundError: If the conventions document is missing, naming it.
        ValueError: If a section could not be parsed, which means the document
            was restructured and this tool needs updating with it.
    """
    if not path.is_file():
        raise FileNotFoundError(f"conventions document not found: {path}")
    buckets: dict[str, set[str]] = {
        "documented": set(),
        "acknowledged": set(),
        "unwanted": set(),
    }
    section = "documented"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            heading = line.lower()
            if "stage id" in heading:
                section = "stages"
            elif "not wanted" in heading:
                section = "unwanted"
            elif "not helpers" in heading:
                section = "acknowledged"
            else:
                section = "documented"
            continue
        if section == "stages":
            continue
        match = _TABLE_ROW.match(line)
        if not match:
            continue
        buckets[section].update(_PREFIX.findall(match.group(1)))
    empty = sorted(name for name, found in buckets.items() if not found)
    if empty:
        raise ValueError(
            f"{path}: could not parse the verb tables; empty sections: "
            f"{', '.join(empty)} -- expected leading '`verb_*`' cells in tables "
            "under a heading naming 'not helpers' and one naming 'not wanted'"
        )
    return buckets["documented"], buckets["acknowledged"], buckets["unwanted"]


def public_functions(package: Path = PACKAGE) -> list[tuple[str, Path]]:
    """Collect every public module-level function in the package, by AST.

    Args:
        package: The package directory to scan.

    Returns:
        ``(function_name, source_file)`` pairs, sorted by name. Methods, nested
        functions and underscore-prefixed helpers are excluded.
    """
    found: list[tuple[str, Path]] = []
    for source in sorted(package.rglob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith("_"):
                continue
            found.append((node.name, source))
    return sorted(found)


def report(check: bool = False) -> int:
    """Print the verb-prefix compliance report.

    Args:
        check: When true, return a non-zero code if an undocumented prefix has
            reached :data:`ESTABLISHED` uses, or a discouraged prefix is used.

    Returns:
        A process exit code: 0 when clean, 1 when ``check`` found drift.
    """
    documented, acknowledged, unwanted = read_documented_prefixes()
    functions = public_functions()
    helpers = [(n, f) for n, f in functions if n not in ENTRY_POINT_NAMES]
    entry_points = len(functions) - len(helpers)

    counts = collections.Counter(name.split("_")[0] for name, _ in helpers)
    # Acknowledged non-verbs (CLI handlers, noun-prefixed families) are neither
    # compliant nor drift: measuring them either way would misreport the table.
    excused = sum(count for verb, count in counts.items() if verb in acknowledged)
    compliant = sum(count for verb, count in counts.items() if verb in documented)
    total = len(helpers) - excused
    rate = 100.0 * compliant / total if total else 100.0

    print(f"public module-level functions   {len(functions)}")
    print(
        f"  entry points (excluded)       {entry_points} "
        f"({', '.join(sorted(ENTRY_POINT_NAMES))})"
    )
    print(f"  noun families / handlers      {excused} (acknowledged, not verbs)")
    print(f"  helpers measured              {total}")
    print(f"documented prefixes             {len(documented)}")
    print(f"compliance                      {compliant}/{total} = {rate:.1f}%")

    drift = {
        verb: count
        for verb, count in counts.items()
        if verb not in documented | acknowledged | unwanted and count >= ESTABLISHED
    }
    discouraged = {verb: count for verb, count in counts.items() if verb in unwanted}

    if drift:
        print(f"\nundocumented prefixes at >= {ESTABLISHED} uses:")
        for verb, count in sorted(drift.items(), key=lambda kv: -kv[1]):
            examples = [n for n, _ in helpers if n.split("_")[0] == verb][:3]
            print(f"  {verb + '_*':<16}{count:>4}  {', '.join(examples)}")
    if discouraged:
        print(
            "\ndiscouraged prefixes still in use (see the guide for the "
            "verb to use instead):"
        )
        for verb, count in sorted(discouraged.items(), key=lambda kv: -kv[1]):
            examples = [n for n, _ in helpers if n.split("_")[0] == verb][:3]
            print(f"  {verb + '_*':<16}{count:>4}  {', '.join(examples)}")

    if check and drift:
        print(
            "\nFAIL: a verb the SDK uses is not in the table. Either rename to a "
            "documented prefix, or add the verb to docs/contributing/"
            "conventions.md with the behaviour it signals.",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the verb-prefix report.

    Args:
        argv: Command-line arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        The process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero when an undocumented prefix has become established",
    )
    args = parser.parse_args(argv)
    return report(check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
