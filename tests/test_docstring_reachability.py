"""Gate: a string written as a docstring must actually BE one.

Why this exists
---------------
``def f(script):`` followed by ``cache_dir = script.cache_dir`` and only THEN a
triple-quoted string does not define a docstring. Python binds ``__doc__`` from
the first statement of a body and nothing else, so the string becomes a no-op
expression: it renders in the source, reads as documentation to every human who
opens the file, and is invisible to ``help()``, ``inspect.getdoc``, mkdocstrings
and any tool that reads ``__doc__``.

Measured 2026-09-09 (bd b7y): **fifteen** functions were in this state, every one
a ``derive_*`` in ``projects/ev_hosting_flex/scripts/pipeline/``. Six of them
also carried ``Args:`` sections describing ``cache_dir`` / ``data_dir`` -- which
are locals, not parameters -- and one named a ``json_dir`` that exists nowhere in
the function. Unreachable text does not get corrected, because nothing reads it.

Why flake8 does not catch it
----------------------------
The tree passes ``flake8`` with ``flake8-docstrings`` loaded (checked: ``flake8
--version`` lists it). ``pydocstyle``'s own parser accepts a string that is not
the first statement, so ``D103`` never fires on this shape. A convention the
repo believes it enforces was unenforced for exactly the case that produced
fifteen instances -- which is the argument for an independent AST check rather
than for tightening the linter.

Scope
-----
Functions, async functions and classes, across every tree flake8 covers plus
``dashboard``. The inventory at authoring time is **0** in all five, so this
gate starts clean and any regression is new.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TREES = ("gridalyn", "projects", "tools", "tests", "dashboard")

_Definition = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


def _orphaned(path: Path) -> list[tuple[str, int, str]]:
    """Return every definition in ``path`` whose docstring is not reachable.

    Args:
        path: A Python source file to scan.

    Returns:
        One ``(qualified name, line of the stray string, kind)`` per offender.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    found: list[tuple[str, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, _Definition):
            continue
        if ast.get_docstring(node) is not None:
            continue
        for statement in node.body[1:]:
            if isinstance(statement, ast.Expr) and isinstance(
                statement.value, ast.Constant
            ):
                if isinstance(statement.value.value, str):
                    kind = "class" if isinstance(node, ast.ClassDef) else "function"
                    found.append((node.name, statement.lineno, kind))
                    break
    return found


class DocstringReachabilityTest(unittest.TestCase):
    """Every string that looks like a docstring must bind to ``__doc__``."""

    def test_no_definition_carries_an_unreachable_docstring(self) -> None:
        """A stray string after a statement documents nothing and nobody reads it."""
        offenders: list[str] = []
        for tree in _TREES:
            root = _REPO_ROOT / tree
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*.py")):
                for name, line, kind in _orphaned(path):
                    rel = path.relative_to(_REPO_ROOT)
                    offenders.append(f"{rel}:{line} {kind} {name}()")
        self.assertEqual(
            offenders,
            [],
            "these strings are written as docstrings but bind to nothing, because "
            "a statement precedes them in the body:\n  "
            + "\n  ".join(offenders)
            + "\nMove the string to be the FIRST statement of the definition. "
            "flake8-docstrings does not catch this shape (bd b7y).",
        )

    def test_the_scan_is_not_vacuous(self) -> None:
        """The detector must fire on the shape, or a clean result proves nothing."""
        with self.subTest("an orphaned docstring is detected"):
            source = "def f(script):\n    d = script.data_dir\n    '''Doc.'''\n    return d\n"
            path = _REPO_ROOT / "tests" / "__orphan_probe.py"
            path.write_text(source, encoding="utf-8")
            try:
                self.assertEqual([("f", 3, "function")], _orphaned(path))
            finally:
                path.unlink()

        with self.subTest("a real docstring is not"):
            source = "def f(script):\n    '''Doc.'''\n    return script\n"
            path = _REPO_ROOT / "tests" / "__orphan_probe.py"
            path.write_text(source, encoding="utf-8")
            try:
                self.assertEqual([], _orphaned(path))
            finally:
                path.unlink()

    def test_a_trailing_string_that_is_not_documentation_is_still_reported(
        self,
    ) -> None:
        """The rule is positional, so a stray string anywhere in a body counts.

        A bare string expression deep in a function is dead code whether or not
        the author meant it as a docstring, so reporting it is correct rather
        than a false positive. Recorded here because a future reader will
        otherwise wonder whether the check is too broad; the inventory is 0, so
        nothing in this tree relies on writing one.
        """
        source = "def f():\n    x = 1\n    'a stray string'\n    return x\n"
        path = _REPO_ROOT / "tests" / "__orphan_probe.py"
        path.write_text(source, encoding="utf-8")
        try:
            self.assertEqual([("f", 3, "function")], _orphaned(path))
        finally:
            path.unlink()


if __name__ == "__main__":
    unittest.main()
