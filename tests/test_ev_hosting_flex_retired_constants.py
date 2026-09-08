"""No constant this study marks RETIRED is read, and none is left standing.

`config.py` deliberately kept retired constants importable, each docstring
naming the consumer that "still references it". Measured 2026-09-04: none of
those consumers existed -- zero reads of any of the ten, repo-wide -- so the
stated reason for keeping them had expired years-of-commits ago while the
constants still read as live. They were deleted in bd 8va.

Two guards, and they answer different questions. The first pins the deletion,
so a revival makes `config.py`'s tombstones and CALIBRATION.md's banners wrong
loudly rather than silently. The second is the one that outlives this cleanup:
ANY constant the file marks RETIRED must have zero reads, so the next one to
be retired-but-kept is caught while the exemption is still fresh.

Resolution is by AST, never by substring. A grep for the one-letter `K` over
the study's scripts returns 38 hits, every one physics prose ("K(T) per step",
"kJ/(kg*K)", "kWh/K"); a substring gate would be permanently red for the wrong
reason and switched off within a week. `tests/test_import_hygiene.py` pins
rdflib at zero the same way.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / "projects" / "ev_hosting_flex" / "scripts" / "config.py"

#: Deleted in bd 8va. Kept as data so the first test states what it pins.
DELETED = frozenset(
    {
        "AVAILABILITY_SCENARIOS",
        "EXTENDED_PENETRATION_SWEEP",
        "K",
        "PLUGIN_WINDOW",
        "TOLERANCE_ACTIVATION_HOURS_MAX",
        "TOLERANCE_CURTAILED_ENERGY_FRACTION_MAX",
        "TOLERANCE_IRREDUCIBLE_LOST_FRACTION_MAX_P95",
        "TOLERANCE_PRIMARY",
        "TOLERANCE_UNSERVED_ENERGY_FRACTION_MAX_P95",
        "WORKPLACE_WINDOW",
    }
)

#: Trees whose modules could import from the study's config.
SCANNED = ("projects", "gridalyn", "tests", "tools")


def _module_constants(path: Path) -> dict[str, str]:
    """Return module-level constant name -> first line of its docstring."""
    body = ast.parse(path.read_text(encoding="utf-8")).body
    out: dict[str, str] = {}
    for index, node in enumerate(body):
        if not (isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)):
            continue
        following = body[index + 1] if index + 1 < len(body) else None
        doc = ""
        if (
            isinstance(following, ast.Expr)
            and isinstance(following.value, ast.Constant)
            and isinstance(following.value.value, str)
        ):
            doc = following.value.value.strip().splitlines()[0]
        out[node.targets[0].id] = doc
    return out


def _read_in_node(node: ast.AST, names: frozenset[str]) -> str | None:
    """Return how ``node`` reads one of ``names``, or None when it does not.

    The two forms a consumer can use: ``from ...config import X`` and
    attribute access on something called config.
    """
    if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("config"):
        found = [alias.name for alias in node.names if alias.name in names]
        return f"import {found[0]}" if found else None
    if isinstance(node, ast.Attribute) and node.attr in names:
        base = node.value
        named = (isinstance(base, ast.Name) and "config" in base.id.lower()) or (
            isinstance(base, ast.Attribute) and "config" in base.attr.lower()
        )
        return ast.unparse(node) if named else None
    return None


def _reads_of(names: frozenset[str]) -> list[str]:
    """Return `path:line  how` for every read of ``names`` outside config.py."""
    hits: list[str] = []
    for tree_name in SCANNED:
        for path in (REPO_ROOT / tree_name).rglob("*.py"):
            if path.resolve() == CONFIG.resolve() or "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                how = _read_in_node(node, names)
                if how is not None:
                    hits.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}  {how}")
    return sorted(hits)


class DeletedConstantsStayDeleted(unittest.TestCase):
    def test_none_of_the_ten_is_defined_again(self) -> None:
        """A revival must fail here, where the tombstones can be corrected."""
        back = sorted(DELETED & set(_module_constants(CONFIG)))
        self.assertEqual(
            [],
            back,
            f"{back} are back in config.py: either delete them again, or remove "
            "their tombstones there and the RETIRED banners in CALIBRATION.md, "
            "because those now describe the wrong tree.",
        )

    def test_the_tombstones_name_what_was_removed(self) -> None:
        """The record in the file must still account for every deleted name."""
        text = CONFIG.read_text(encoding="utf-8")
        self.assertIn("DELETED (bd 8va", text)
        missing = sorted(name for name in DELETED if name not in text)
        self.assertEqual([], missing, f"tombstones no longer name {missing}")


class RetiredConstantsAreUnread(unittest.TestCase):
    def test_every_retired_constant_has_zero_reads(self) -> None:
        """The general guard: RETIRED and read is a contradiction.

        Fails naming the reader, so the choice is explicit -- unretire the
        constant, or re-point the reader -- rather than a stale exemption
        nobody revisits.
        """
        retired = frozenset(
            name
            for name, doc in _module_constants(CONFIG).items()
            if "RETIRED" in doc.upper()
        )
        hits = _reads_of(retired) if retired else []
        self.assertEqual(
            [],
            hits,
            "constants marked RETIRED in config.py are still read:\n  "
            + "\n  ".join(hits),
        )

    def test_the_scan_is_not_vacuous(self) -> None:
        """A scanner that resolves nothing would pass while proving nothing."""
        live = frozenset({"SEED", "TRIAGE_K_BASE"})
        self.assertTrue(
            _reads_of(live),
            "the AST scan found no reads of SEED or TRIAGE_K_BASE, which the "
            "pipeline certainly imports -- the resolver is broken, not the tree",
        )
