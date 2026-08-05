"""Gate: every conditional skip in ``tests/`` announces why it did not run.

Why this exists
---------------
The heavy-study reproduce-and-pin tests skip when their gitignored outputs are
absent. In CI they skip silently, so a green summary cannot tell an operator
whether the expensive verification actually happened. This module makes the
skip surface auditable: it AST-scans ``tests/`` and enforces that every
conditional skip supplies a reason specific enough to act on.

Inventory recorded at authoring time (2026-08-05)
-------------------------------------------------
- **46** conditional-skip call sites across **26** test files.
- Note ``grep -rln "skipif|pytest.skip|self.skipTest" tests/`` reports only
  **23** files; it misses ``unittest.skipUnless`` / ``skipIf``. The AST scan is
  the authoritative count.
- Mechanisms: ``pytest.mark.skipif`` 40, ``unittest.skipUnless`` 3,
  ``pytest.skip`` 2, ``self.skipTest`` 1.
- Reason status: **11** static string literals, **35** resolved from a
  module-level string constant (the ``_SKIP`` / ``_SKIP_REASON`` idiom),
  **0** dynamic (f-string/concatenation), **0** missing.

The specificity rule (deterministic, not a judgement call)
----------------------------------------------------------
A reason is rejected if, after normalisation, it fails **either** clause:

1. **Length** - fewer than ``_MIN_REASON_CHARS`` (20) characters.
2. **Denylist** - it matches an entry in ``_GENERIC_REASONS`` exactly.

Normalisation is: collapse all whitespace runs to single spaces, strip
surrounding whitespace and punctuation, lowercase. Matching is exact, so
``"not installed"`` is rejected while ``"hypothesis is not installed"`` is
accepted - the denylist catches placeholders, not substrings.

Both clauses carry weight: ``"temporarily disabled"`` is exactly 20 characters
and so passes clause 1, but is rejected by clause 2.

The threshold was chosen against the real corpus, not to fit it: at 20 chars
**no** existing skip fails, and the shortest real reason is 21 characters
(``"topology cache absent"``). A stricter 25 would fail 2 existing skips,
which per this phase's stop gates would require its own remediation plan
rather than a weakened rule.

The static blind spot
---------------------
A reason built by an f-string or concatenation cannot be checked for content
statically. Such sites are counted as ``DYNAMIC`` and are exempt from clauses
1 and 2, so the blind spot is measured rather than hidden. It is **0** today,
because every non-literal reason in this suite is a module-level constant that
the scanner resolves. Dynamic sites are still held to the weaker rule that a
reason argument must be *present* - only its content is unverifiable.

Known-weak reasons (reported, not enforced)
-------------------------------------------
Three reasons pass the rule but name only what is missing, not how to obtain
it. Fixing them means editing other test files, which is out of scope here:

- ``tests/test_ev_hosting_flex_phase.py:73`` - "topology cache absent"
- ``tests/test_ev_hosting_flex_insurance.py:105`` - "credibility.json absent"
- ``tests/test_project_hygiene.py:845`` - "minimal tutorial dataset has not
  been created yet"
"""

from __future__ import annotations

import ast
import unittest
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TESTS_DIR = _REPO_ROOT / "tests"

# Skip mechanism -> index of the positional argument carrying the reason.
# ``pytest.mark.skipif(cond, reason)`` and ``unittest.skipIf/skipUnless(cond,
# reason)`` put it second; ``pytest.skip(reason)`` and
# ``self.skipTest(reason)`` put it first. Every mechanism also accepts
# ``reason=`` by keyword, which takes precedence.
_REASON_POSITION = {
    "skipif": 1,
    "skipIf": 1,
    "skipUnless": 1,
    "skip": 0,
    "skipTest": 0,
}

# Reason resolution outcomes.
_STATIC = "STATIC"  # a string literal at the call site
_RESOLVED = "RESOLVED"  # a module-level string constant, resolved by name
_DYNAMIC = "DYNAMIC"  # f-string/concat/call - content not checkable statically
_MISSING = "MISSING"  # no reason argument supplied at all

_CHECKABLE = (_STATIC, _RESOLVED)

# Clause 1 of the specificity rule. See the module docstring for the rationale.
_MIN_REASON_CHARS = 20

# Clause 2: normalised reasons that match one of these exactly are placeholders
# rather than explanations. Matching is exact, so a longer reason that merely
# contains one of these phrases is accepted.
_GENERIC_REASONS = frozenset(
    {
        "",
        "skip",
        "skipped",
        "skipping",
        "skip this",
        "skip test",
        "n/a",
        "na",
        "tbd",
        "todo",
        "fixme",
        "xfail",
        "broken",
        "flaky",
        "wip",
        "unavailable",
        "not available",
        "not supported",
        "not implemented",
        "not installed",
        "not ready",
        "not found",
        "no reason",
        "reason",
        "missing",
        "disabled",
        "temporarily disabled",
        "does not work",
        "doesn't work",
        "fails",
        "failing",
        "later",
        "for now",
        "see above",
    }
)


def normalize_reason(reason: str) -> str:
    """Collapse whitespace, strip surrounding punctuation, and lowercase."""
    collapsed = " ".join(reason.split())
    return collapsed.strip(" \t\r\n.,:;!?-_*()[]'\"").lower()


def reason_rejection(reason: str) -> str:
    """Return why a reason is rejected, or ``""`` if it is acceptable.

    Deterministic by construction: a length threshold plus an exact-match
    denylist, both stated in the module docstring.
    """
    normalized = normalize_reason(reason)
    if normalized in _GENERIC_REASONS:
        return f"generic placeholder (denylisted): {reason!r}"
    if len(normalized) < _MIN_REASON_CHARS:
        return f"too short: {len(normalized)} < {_MIN_REASON_CHARS} chars: {reason!r}"
    return ""


@dataclass(frozen=True)
class SkipSite:
    """One conditional-skip call site found in the test tree."""

    relative_path: str
    line: int
    mechanism: str
    status: str
    reason: str

    def located(self) -> str:
        """Return a ``file:line (mechanism)`` locator for failure messages."""
        return f"{self.relative_path}:{self.line} ({self.mechanism})"


def _callee_name(node: ast.expr) -> str:
    """Return the trailing attribute or bare name of a call target."""
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _callee_prefix(node: ast.expr) -> str:
    """Return the dotted prefix of a call target, for reporting."""
    if isinstance(node, ast.Attribute):
        return ast.unparse(node.value)
    return ""


def _module_string_constants(tree: ast.Module) -> dict[str, str]:
    """Map module-level ``NAME = "literal"`` assignments to their values.

    This resolves the ``_SKIP`` / ``_SKIP_REASON`` idiom used throughout the
    heavy-study tests, so those reasons are checkable rather than blind.
    """
    constants: dict[str, str] = {}
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        value = statement.value
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            continue
        for target in statement.targets:
            if isinstance(target, ast.Name):
                constants[target.id] = value.value
    return constants


def _reason_expression(node: ast.Call, mechanism: str) -> ast.expr | None:
    """Return the AST node supplying the reason, keyword first then positional."""
    for keyword in node.keywords:
        if keyword.arg == "reason":
            return keyword.value
    position = _REASON_POSITION[mechanism]
    if len(node.args) > position:
        return node.args[position]
    return None


def scan_skip_sites() -> list[SkipSite]:
    """AST-scan ``tests/`` and return every conditional-skip call site."""
    sites: list[SkipSite] = []
    for path in sorted(_TESTS_DIR.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        constants = _module_string_constants(tree)
        relative_path = path.relative_to(_REPO_ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _callee_name(node.func)
            if name not in _REASON_POSITION:
                continue
            prefix = _callee_prefix(node.func)
            mechanism = f"{prefix}.{name}" if prefix else name
            expression = _reason_expression(node, name)
            if expression is None:
                status, reason = _MISSING, ""
            elif isinstance(expression, ast.Constant) and isinstance(
                expression.value, str
            ):
                status, reason = _STATIC, expression.value
            elif isinstance(expression, ast.Name) and expression.id in constants:
                status, reason = _RESOLVED, constants[expression.id]
            else:
                status, reason = _DYNAMIC, ast.unparse(expression)
            sites.append(
                SkipSite(
                    relative_path=relative_path,
                    line=node.lineno,
                    mechanism=mechanism,
                    status=status,
                    reason=reason,
                )
            )
    return sites


class SkipInventoryTest(unittest.TestCase):
    """The scanner itself must not go false-green by matching nothing."""

    def test_scan_finds_a_non_trivial_number_of_skip_sites(self) -> None:
        sites = scan_skip_sites()

        # A scanner that silently matches nothing would make every other
        # assertion in this module vacuously true. Pin a floor well below the
        # 46 sites found at authoring time so ordinary cleanup does not trip
        # it, but a broken scanner does.
        self.assertGreaterEqual(
            len(sites),
            20,
            "skip scanner found almost nothing - it is probably broken, "
            f"not the suite: {len(sites)} site(s)",
        )

    def test_scan_detects_every_supported_skip_mechanism(self) -> None:
        mechanisms = {site.mechanism for site in scan_skip_sites()}

        # Each of these is in real use in this suite. Losing detection of one
        # would hide a whole class of skip.
        for expected in ("pytest.mark.skipif", "unittest.skipUnless"):
            with self.subTest(mechanism=expected):
                self.assertIn(expected, mechanisms)

    def test_reason_status_partitions_every_site(self) -> None:
        sites = scan_skip_sites()
        known = {_STATIC, _RESOLVED, _DYNAMIC, _MISSING}

        unclassified = [site.located() for site in sites if site.status not in known]

        self.assertEqual([], unclassified)


class SkipReasonSpecificityTest(unittest.TestCase):
    """A skip with no reason, or a placeholder reason, must fail the gate."""

    def test_every_skip_site_supplies_a_reason(self) -> None:
        offenders = [
            site.located() for site in scan_skip_sites() if site.status == _MISSING
        ]

        self.assertEqual(
            [],
            offenders,
            "conditional skip(s) with no reason at all - an operator cannot "
            "tell what did not run:\n  " + "\n  ".join(offenders),
        )

    def test_checkable_skip_reasons_are_specific(self) -> None:
        offenders = []
        for site in scan_skip_sites():
            if site.status not in _CHECKABLE:
                continue
            rejection = reason_rejection(site.reason)
            if rejection:
                offenders.append(f"{site.located()}: {rejection}")

        self.assertEqual(
            [],
            offenders,
            "skip reason(s) too generic to act on - say what is missing and "
            "how to obtain it:\n  " + "\n  ".join(offenders),
        )

    def test_dynamic_reasons_are_measured_not_hidden(self) -> None:
        sites = scan_skip_sites()
        dynamic = [site for site in sites if site.status == _DYNAMIC]

        # Content of an f-string/concatenated reason cannot be checked
        # statically, so these are exempt from the specificity clauses. They
        # are counted here so the gate's blind spot stays visible: it was 0 of
        # 46 sites at authoring time. This assertion keeps the exemption from
        # becoming an escape hatch - the blind spot may not swallow the suite.
        self.assertLess(
            len(dynamic),
            max(1, len(sites) // 2),
            "over half of all skip reasons are now built dynamically; the "
            "specificity gate can no longer see most of the suite:\n  "
            + "\n  ".join(f"{s.located()}: {s.reason}" for s in dynamic),
        )


if __name__ == "__main__":
    unittest.main()
