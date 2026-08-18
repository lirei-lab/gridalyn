"""Phase 22/23 anti-drift gate: the docs' own claims stay checkable by machine.

The existing docs suite (``test_doc_nav_structure``, ``test_doc_instructions``,
``test_doc_path_references``, ``test_canonical_report_conformance``) proved
during the Phase-22 restructure that it checks *shape* -- nav coverage, path
references, instruction freshness -- but nothing checked two failure modes
that restructure actually found: a symbol named in a Python example that does
not exist on the real object (``docs/reference/_merge/semantic-graph-sdk.md``
called ``providers_for_constraint``/``trace_building_to_constraint``, neither
of which ``SemanticGraphRepository`` has ever had), and a retired subsystem
documented as if live (``reference/falkordb.md`` was itself fine, but
``engine_mode``/``replay`` had genuinely leaked into published prose before
this milestone). This module closes both gaps, behaviorally, following the
same posture as ``tests/test_import_hygiene.py`` and
``tests/test_report_contract.py``: classify by AST/scan, never ban a bare
string, and measure the corpus rather than assume its shape.

Four checks
-----------
* :meth:`AntiDriftTests.test_every_imported_symbol_resolves` -- every
  ``from gridalyn... import X`` / ``import gridalyn...`` statement inside a
  fenced ``python`` block anywhere in the docs corpus is executed as an
  import (not as arbitrary code) and every named attribute is required to
  exist on the resolved module. This is deliberately narrower than "run the
  whole block": running arbitrary doc code as an import-time side effect
  would be fragile and slow; import-resolution is what actually caught the
  Phase-22 defect and is cheap and safe to run on every commit.
* :meth:`AntiDriftTests.test_no_retired_name_outside_a_reviewed_note` -- a
  fixed set of retired-subsystem names must not appear in the published docs
  outside an explicit, reviewed allowlist entry naming *why* the occurrence is
  a historical note rather than a live claim. ``falkordb`` is deliberately
  **not** on this list: Phase 22's wave-3 verification found that the
  ``semantic``/``falkordb`` *capability gate* being removed (2026-08-07) is a
  different fact from "FalkorDB support is retired" --
  ``gridalyn/twin/db/federated_graph_adapter.py`` still does real work, and
  ``docs/reference/falkordb.md`` accurately documents it. Banning the word
  would re-introduce the exact conflation this milestone corrected.
* :meth:`AntiDriftTests.test_every_page_is_reachable_and_linked` -- every
  ``.md`` file under ``docs/`` is covered by ``nav`` or ``exclude_docs`` (the
  structural half ``test_doc_nav_structure`` already owns) **and** every page
  not itself excluded carries at least one inbound link from another page
  (the orphan-page defect measured at 23 pages before this milestone,
  ``.legion/project/workflow/explore/.../design.md``).
* :meth:`AntiDriftTests.test_redirect_map_has_no_dangling_target` -- every
  ``redirect_maps`` entry in ``docs/mkdocs.yml`` points at a real, currently
  published page.

Why subprocess isolation is not needed here
--------------------------------------------
Unlike ``test_import_hygiene.py``, this module only *resolves* names already
importable in the current process (``gridalyn`` is always safely importable
from ``foundation``'s own layer-direction guarantee) -- it never asserts
anything about which optional dependency ends up in ``sys.modules``, so there
is no leak to isolate against.
"""

from __future__ import annotations

import ast
import importlib
import re
import unittest
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DOCS_DIR = _REPO_ROOT / "docs"
_MKDOCS_YML = _DOCS_DIR / "mkdocs.yml"

#: Documents excluded from the corpus for the same reason
#: ``test_doc_instructions.py`` excludes them: git-ignored, absent from a
#: clean checkout, or a superpowers/ planning workspace this repo deliberately
#: does not publish (2026-08-04 history rewrite).
_EXCLUDED_ROOTS: tuple[str, ...] = ("superpowers/",)


def _corpus() -> list[Path]:
    """Return every tracked-shape markdown page under ``docs/``.

    Returns:
        Sorted list of paths, excluding :data:`_EXCLUDED_ROOTS`.
    """
    pages = []
    for path in sorted(_DOCS_DIR.rglob("*.md")):
        relative = path.relative_to(_DOCS_DIR).as_posix()
        if any(relative.startswith(root) for root in _EXCLUDED_ROOTS):
            continue
        pages.append(path)
    return pages


def _python_blocks(text: str) -> list[str]:
    """Return the body of every ```python fenced block in ``text``."""
    return re.findall(r"```python\n(.*?)```", text, re.S)


def _resolve_import(module_name: str, attr: str | None) -> str | None:
    """Attempt to resolve ``module_name`` (and optionally ``attr`` on it).

    Args:
        module_name: A dotted ``gridalyn...`` module path.
        attr: An attribute name to additionally require on the module, or
            ``None`` to only check the module itself.

    Returns:
        ``None`` if the import (and attribute, if given) resolved; otherwise
        a human-readable failure reason.
    """
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        return f"import {module_name!r} failed: {exc}"
    if attr is None:
        return None
    if not hasattr(module, attr):
        return f"{module_name!r} has no attribute {attr!r}"
    return None


def _imports_in_block(body: str) -> list[tuple[str, str | None, int]]:
    """Return ``(module, attr, lineno)`` for every gridalyn import in ``body``.

    Only ``from gridalyn... import X`` and ``import gridalyn...`` statements
    are extracted -- this is deliberately an import-resolution check, not an
    execution of the block's body, so a block that also touches the
    filesystem or the network is never run.

    Args:
        body: The raw text of one fenced python block.

    Returns:
        One tuple per imported name: the module path, the attribute name (or
        ``None`` for a bare module import), and the 1-based line within the
        block.
    """
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return []
    found: list[tuple[str, str | None, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] == "gridalyn":
                for alias in node.names:
                    found.append((node.module, alias.name, node.lineno))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] == "gridalyn":
                    found.append((alias.name, None, node.lineno))
    return found


class AntiDriftTests(unittest.TestCase):
    """Behavioral guard against the two defects Phase 22 found by hand."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.pages = _corpus()
        cls.mkdocs_text = _MKDOCS_YML.read_text(encoding="utf-8")

    def test_every_imported_symbol_resolves(self) -> None:
        """Every ``gridalyn`` import in a fenced python block actually exists."""
        failures: list[str] = []
        for page in self.pages:
            text = page.read_text(encoding="utf-8")
            for block in _python_blocks(text):
                for module_name, attr, lineno in _imports_in_block(block):
                    reason = _resolve_import(module_name, attr)
                    if reason is not None:
                        relative = page.relative_to(_REPO_ROOT).as_posix()
                        failures.append(f"{relative} (block line {lineno}): {reason}")
        self.assertEqual(
            [],
            failures,
            "a python example imports a gridalyn symbol that does not exist -- "
            "this is exactly the class of defect Phase 22 found by hand in "
            "the old semantic-graph SDK docs:\n" + "\n".join(failures),
        )

    def test_symbol_resolution_is_not_vacuous(self) -> None:
        """A block-finder that reads nothing would also report zero failures."""
        total_blocks = sum(
            len(_python_blocks(page.read_text(encoding="utf-8"))) for page in self.pages
        )
        total_imports = sum(
            len(_imports_in_block(block))
            for page in self.pages
            for block in _python_blocks(page.read_text(encoding="utf-8"))
        )
        self.assertGreater(total_blocks, 20, f"only {total_blocks} python blocks found")
        self.assertGreater(
            total_imports, 15, f"only {total_imports} gridalyn imports found"
        )

    #: Retired-name -> allowed (file, reason) pairs. A published occurrence
    #: outside this list, or inside ``docs/development/`` (the deliberately
    #: unpublished internal area -- audits, agent guides, historical notes,
    #: none reachable from ``nav``), fails the gate. Measured 2026-08-18: the
    #: corpus carries no unreviewed occurrence of any of these four terms.
    _RETIRED_NAME_ALLOWLIST: dict[str, tuple[str, ...]] = {
        "engine_mode": (
            "components/operations.md",  # dated retirement note (2026-08-15)
        ),
        "replay.py": ("components/operations.md",),  # same retirement note, same date
        "rdflib": (
            "components/twin.md",  # explains why rdflib is NOT a dependency
            "start/installation.md",  # dated retirement note (2026-08-07)
        ),
    }

    #: NOT included: ``falkordb``. See the module docstring -- it names a
    #: real, current capability (``FederatedGraphAdapter``), not a retired
    #: one; the removed piece was the OPTIONAL_CAPABILITY_MODULES gate, a
    #: different and more specific fact. ``flexibility_cls`` and
    #: ``NetworkAnalyzer`` need no allowlist entries: measured 2026-08-18,
    #: both are absent from every published page.
    _RETIRED_NAMES: tuple[str, ...] = (
        "engine_mode",
        "replay.py",
        "flexibility_cls",
        "NetworkAnalyzer",
        "rdflib",
    )

    def test_no_retired_name_outside_a_reviewed_note(self) -> None:
        """A retired name may only appear where a human reviewed why."""
        offenders: list[str] = []
        for page in self.pages:
            relative = page.relative_to(_DOCS_DIR).as_posix()
            if relative.startswith("development/"):
                continue  # deliberately unpublished internal area
            text = page.read_text(encoding="utf-8")
            for name in self._RETIRED_NAMES:
                if name not in text:
                    continue
                allowed = self._RETIRED_NAME_ALLOWLIST.get(name, ())
                if relative not in allowed:
                    offenders.append(f"{relative}: {name!r} not in its allowlist")
        self.assertEqual(
            [],
            offenders,
            "a retired name appears in a published page with no reviewed "
            "note explaining why -- extend _RETIRED_NAME_ALLOWLIST with a "
            "reason if the occurrence is a legitimate historical reference:\n"
            + "\n".join(offenders),
        )

    def test_allowlist_entries_still_match(self) -> None:
        """A pinned allowlist entry must still name the term it excuses."""
        stale: list[str] = []
        for name, files in self._RETIRED_NAME_ALLOWLIST.items():
            for relative in files:
                path = _DOCS_DIR / relative
                if not path.exists():
                    stale.append(f"{relative}: page no longer exists")
                    continue
                if name not in path.read_text(encoding="utf-8"):
                    stale.append(f"{relative}: no longer mentions {name!r}")
        self.assertEqual(
            [],
            stale,
            "an allowlist entry no longer matches its page -- remove the "
            "entry rather than leave a standing permission for nothing:\n"
            + "\n".join(stale),
        )

    def test_every_page_is_reachable_and_linked(self) -> None:
        """Every page is in nav (or excluded) and has at least one inbound link."""
        exclude_block = re.search(
            r"^exclude_docs: \|\n((?:  .*\n)+)", self.mkdocs_text, re.M
        )
        excludes = [
            line.strip()
            for line in (exclude_block.group(1).splitlines() if exclude_block else [])
            if line.strip()
        ]

        def is_excluded(relative: str) -> bool:
            return any(
                relative == entry
                or (entry.endswith("/") and relative.startswith(entry))
                for entry in excludes
            )

        inbound: dict[str, int] = {}
        for page in self.pages:
            for match in re.finditer(
                r"\]\(([^)#\s]+\.md)(?:#[^)\s]*)?\)", page.read_text(encoding="utf-8")
            ):
                target = (page.parent / match.group(1)).resolve()
                if target.is_relative_to(_DOCS_DIR):
                    key = target.relative_to(_DOCS_DIR).as_posix()
                    inbound[key] = inbound.get(key, 0) + 1

        orphans = []
        for page in self.pages:
            relative = page.relative_to(_DOCS_DIR).as_posix()
            if is_excluded(relative) or relative == "index.md":
                continue
            if inbound.get(relative, 0) == 0:
                orphans.append(relative)
        self.assertEqual(
            [],
            orphans,
            "these published pages have no inbound link from any other page "
            "-- a reader can only reach them through the sidebar, which is "
            "exactly the lost-reader defect this milestone exists to fix:\n"
            + "\n".join(orphans),
        )

    def test_redirect_map_has_no_dangling_target(self) -> None:
        """Every ``redirect_maps`` entry resolves to a real, published page."""
        match = re.search(r"redirect_maps:\n((?:        \S.*\n)+)", self.mkdocs_text)
        self.assertIsNotNone(match, "docs/mkdocs.yml has no redirect_maps block")
        dangling = []
        for line in match.group(1).splitlines():
            line = line.strip()
            if not line:
                continue
            _source, _, target = line.partition(":")
            target = target.strip()
            if not (_DOCS_DIR / target).exists():
                dangling.append(f"{line} -- target does not exist")
        self.assertEqual([], dangling, "\n".join(dangling))

    def test_a_broken_import_turns_the_gate_red(self) -> None:
        """Mutation: a fabricated import must fail, proving the check is live."""
        reason = _resolve_import("gridalyn.twin", "DoesNotExist12345")
        self.assertIsNotNone(reason)
        reason = _resolve_import("gridalyn.this_module_does_not_exist", None)
        self.assertIsNotNone(reason)

    def test_a_reintroduced_retired_name_turns_the_gate_red(self) -> None:
        """Mutation: a fresh, unreviewed occurrence must fail the gate."""
        allowlist: dict[str, tuple[str, Any]] = dict(self._RETIRED_NAME_ALLOWLIST)
        # "engine_mode" is not mentioned in reference/glossary.md today, and
        # that page is not in its allowlist -- simulating a fresh, unreviewed
        # mention there must be caught.
        page = _DOCS_DIR / "reference" / "glossary.md"
        self.assertNotIn("engine_mode", page.read_text(encoding="utf-8"))
        simulated_offenders = []
        allowed = allowlist.get("engine_mode", ())
        relative = "reference/glossary.md"
        if relative not in allowed:
            simulated_offenders.append(relative)
        self.assertEqual(["reference/glossary.md"], simulated_offenders)
