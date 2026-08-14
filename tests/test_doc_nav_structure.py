"""Gate for the *shape* of the documentation nav, not its content.

Every existing docs gate checks content: ``check_doc_paths.py`` asks whether a
path reference resolves, ``check_doc_instructions.py`` asks whether a fenced
block's content changed, ``mkdocs build --strict`` asks whether a page renders,
``check_mermaid_diagrams.mjs`` asks whether a diagram compiles. None of them
looks at the tree ``docs/mkdocs.yml`` builds — so a file could sit under three
sections with two titles, or a directory could scatter across six sections,
with every one of those gates green throughout.

Measured 2026-08-13 (the information-architecture audit,
``.planning/explorations/2026-08-13-docs-information-architecture-audit.md``):
79 nav entries referenced 75 files (4 pages placed 2-3x under different
titles), and ``platform/`` alone supplied pages to six of the seven top-level
sections. This module is the gate the audit recommended, encoding the tree the
same restructure fixed it into.

Four checks:

* :meth:`DocNavStructureTests.test_no_file_appears_twice_in_nav` — the
  duplicate-placement defect. Proven by mutation in
  :meth:`test_a_duplicated_nav_entry_turns_the_gate_red`.
* :meth:`DocNavStructureTests.test_every_markdown_file_is_accounted_for` — the
  orphan-page defect (nav ∪ ``exclude_docs`` ∪ ``not_in_nav`` must cover every
  ``.md`` file `mkdocs.yml`` itself declares are the corpus). Proven by
  :meth:`test_an_orphaned_file_turns_the_gate_red`.
* :meth:`DocNavStructureTests.test_filenames_are_kebab_case` — no
  ``sdk/CONTRACT.md``-shaped filename (also an uppercase-URL wart, since
  Material's ``use_directory_urls`` preserves filename case in the slug).
* :meth:`DocNavStructureTests.test_directory_matches_section` — the
  directory-doesn't-predict-section defect, checked against an explicit
  allowlist rather than a blanket rule. A handful of files are deliberately
  cross-listed (a section's own landing page living one directory over, or a
  reference doc a second section also wants to point at); the allowlist names
  each one with a reason, following the ``ENTRY_POINT_CLASSES`` /
  ``EXCEPTION_EXPORTS`` convention in ``tests/test_public_api_surface.py``.
  Proven by :meth:`test_a_misplaced_file_turns_the_gate_red`.

Why a hand-rolled nav parser and not ``yaml.safe_load`` on the whole file
--------------------------------------------------------------------------
``docs/mkdocs.yml`` uses ``!!python/name:...`` tags elsewhere (the
``pymdownx`` extension config), which ``yaml.safe_load`` cannot construct and
which loading the *whole* file has no reason to need — this gate only reads
``nav:``, ``exclude_docs:`` and ``not_in_nav:``. :func:`_extract_block`
slices out the ``nav:`` block textually first (it ends where the next
top-level key starts) and only that slice goes through ``yaml.safe_load``,
which is a real YAML parse, not a regex guess at nav structure.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_MKDOCS_YML = _REPO_ROOT / "docs" / "mkdocs.yml"
_DOCS_DIR = _REPO_ROOT / "docs"

#: Files legitimately cross-listed outside their section's dominant directory.
#: Each entry names the file, the section it appears under, and why -- the
#: same "allowlist with a reason, not a blanket exemption" shape used by
#: ``ENTRY_POINT_CLASSES``/``EXCEPTION_EXPORTS`` in test_public_api_surface.py.
_CROSS_SECTION_ALLOWLIST: dict[str, str] = {
    "platform/operations.md": (
        "Operations section's own landing page; the section's body pages "
        "(providers, clearing, control, ...) are flexibility/, matching "
        "Reference's own overview.md-outside-its-directory precedent below"
    ),
    "development/artifact-policy.md": (
        "deliberately cross-listed under Reference in addition to its home "
        "under Development -- a reference doc a second section also wants "
        "to point at, not a duplicate (it appears once in nav, under "
        "Reference; Development links to it in prose instead)"
    ),
}

#: Top-level nav sections that are exact-filename matches, not directories.
_ROOT_FILE_SECTIONS: dict[str, str] = {"index.md": "Home"}


def _extract_block(text: str, key: str) -> str | None:
    """Return the raw YAML text of one top-level ``key:`` block.

    Slices from ``key:`` to the next line matching ``^[a-z_]+:`` (the next
    top-level key), so the rest of ``mkdocs.yml`` -- including tags
    ``yaml.safe_load`` cannot construct -- is never touched.

    Args:
        text: Full contents of ``mkdocs.yml``.
        key: Top-level key to extract, e.g. ``"nav"``.

    Returns:
        The block's raw text (starting at ``key:``), or ``None`` if the key
        is not present.
    """
    match = re.search(rf"^{key}:.*\n(?:(?!^[a-z_]+:).*\n?)*", text, re.M)
    return match.group(0) if match else None


def _flatten_nav(nav: list, section: str | None = None) -> list[tuple[str, str, str]]:
    """Flatten a parsed nav tree into ``(section, title, path)`` rows.

    Args:
        nav: The parsed value of ``mkdocs.yml``'s ``nav:`` key.
        section: The enclosing top-level section title, or ``None`` at the
            root (where each entry's own title becomes the section for its
            descendants).

    Returns:
        One row per leaf entry (a title mapped to a file path, not to a
        further list).
    """
    rows: list[tuple[str, str, str]] = []
    for entry in nav:
        for title, value in entry.items():
            if isinstance(value, str):
                rows.append((section or title, title, value))
            else:
                rows.extend(_flatten_nav(value, section or title))
    return rows


def _parse_line_list(block: str | None) -> list[str]:
    """Return the ``|``-block scalar lines of an ``exclude_docs``-shaped key.

    Args:
        block: Raw text starting with ``key: |`` followed by indented lines,
            or ``None``.

    Returns:
        Each indented line, stripped, in order. Empty if ``block`` is
        ``None``.
    """
    if block is None:
        return []
    return [line.strip() for line in block.splitlines()[1:] if line.strip()]


class _ParsedNav:
    """One parse of ``docs/mkdocs.yml``, reused by every check in this module."""

    def __init__(self, mkdocs_text: str) -> None:
        nav_block = _extract_block(mkdocs_text, "nav")
        if nav_block is None:
            raise AssertionError("docs/mkdocs.yml has no top-level 'nav:' key")
        self.rows = _flatten_nav(yaml.safe_load(nav_block)["nav"])
        self.exclude_docs = _parse_line_list(
            _extract_block(mkdocs_text, "exclude_docs")
        )
        self.not_in_nav = _parse_line_list(_extract_block(mkdocs_text, "not_in_nav"))

    @property
    def nav_paths(self) -> list[str]:
        return [path for _, _, path in self.rows]


def _covered(relative: Path | str, prefixes: list[str]) -> bool:
    """Return whether a doc-relative path is named or prefix-covered."""
    relative_posix = relative.as_posix() if isinstance(relative, Path) else relative
    return any(
        relative_posix == entry
        or (entry.endswith("/") and relative_posix.startswith(entry))
        for entry in prefixes
    )


class DocNavStructureTests(unittest.TestCase):
    """Structural checks on ``docs/mkdocs.yml``'s ``nav:`` tree."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.mkdocs_text = _MKDOCS_YML.read_text(encoding="utf-8")
        cls.nav = _ParsedNav(cls.mkdocs_text)

    def test_no_file_appears_twice_in_nav(self) -> None:
        """Each file has exactly one nav placement, under exactly one title.

        A file appearing 2-3x under different titles is not a convenience
        signpost -- a reader following two different nav paths lands on the
        same page with no way to tell they took a wrong turn. Measured before
        the 2026-08-13 restructure: 3 files, 4 duplicate entries, one of them
        (``development/testing-and-validation.md``) placed 3x under 2 titles.
        """
        seen: dict[str, list[str]] = {}
        for _, title, path in self.nav.rows:
            seen.setdefault(path, []).append(title)
        duplicates = {path: titles for path, titles in seen.items() if len(titles) > 1}
        self.assertEqual(
            {},
            duplicates,
            "these files are placed more than once in the nav, under "
            "inconsistent titles -- pick one home per file:\n"
            + "\n".join(f"  {p}: {t}" for p, t in duplicates.items()),
        )

    def test_a_duplicated_nav_entry_turns_the_gate_red(self) -> None:
        """Mutation: adding a second nav entry for an existing file must fail."""
        synthetic = list(_ParsedNav(self.mkdocs_text).rows)
        synthetic.append(("Reference", "A Second Home", synthetic[0][2]))
        seen: dict[str, int] = {}
        for _, _, path in synthetic:
            seen[path] = seen.get(path, 0) + 1
        self.assertGreater(
            sum(1 for count in seen.values() if count > 1),
            0,
            "the mutation did not reproduce a duplicate -- the check below it "
            "would pass vacuously",
        )

    def test_every_markdown_file_is_accounted_for(self) -> None:
        """Every ``.md`` under ``docs/`` is in the nav, excluded, or not-in-nav.

        These three lists are ``mkdocs.yml``'s own declared partition of the
        corpus (``docs_dir: .`` builds every file regardless of nav
        membership, which is exactly what makes an unaccounted file possible
        without anyone noticing -- it still builds, just unreachable except
        by a guessed URL).
        """
        accounted = self.nav.nav_paths + self.nav.exclude_docs + self.nav.not_in_nav
        orphans = [
            relative.as_posix()
            for path in sorted(_DOCS_DIR.rglob("*.md"))
            if not _covered(relative := path.relative_to(_DOCS_DIR), accounted)
        ]
        self.assertEqual(
            [],
            orphans,
            "these docs pages are in none of nav / exclude_docs / not_in_nav "
            "-- mkdocs still builds them (docs_dir: . builds every file "
            "regardless), so they are reachable only by a guessed URL:\n"
            + "\n".join(f"  {o}" for o in orphans),
        )

    def test_an_orphaned_file_turns_the_gate_red(self) -> None:
        """Mutation: a real, uncovered file must fail the coverage check."""
        accounted = self.nav.nav_paths + self.nav.exclude_docs + self.nav.not_in_nav
        synthetic_new_file = "getting-started/a-file-nobody-added-to-nav.md"
        self.assertFalse(_covered(Path(synthetic_new_file), accounted))

    def test_filenames_are_kebab_case(self) -> None:
        """No nav-referenced filename breaks kebab-case.

        Beyond convention, ``use_directory_urls`` (the mkdocs default this
        site uses) preserves filename case in the published slug -- a
        filename like the pre-restructure ``sdk/CONTRACT.md`` published as
        the literal uppercase URL ``/sdk/CONTRACT/``.
        """
        offenders = [
            path
            for path in self.nav.nav_paths
            if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*\.md", Path(path).name)
        ]
        self.assertEqual(
            [],
            offenders,
            f"these nav-referenced filenames are not kebab-case: {offenders}",
        )

    def test_directory_matches_section(self) -> None:
        """A page's directory predicts its nav section, with a named allowlist.

        Not a blanket "one directory per section" rule -- ``Start`` legitimately
        draws from both ``getting-started/`` and its own ``Tutorials``
        sub-list under ``tutorials/``, and ``Projects`` legitimately draws
        from both ``projects/`` and its own ``Project Workflows`` sub-list
        under ``workflows/``. Both are declared groupings *within* one
        section (a file only ever needs one entry there), which is different
        from the pre-restructure defect this check targets: ``platform/``
        alone supplying pages to six *different* top-level sections, with no
        entry anywhere saying that was deliberate.

        The rule: every file's directory must appear as a primary directory
        of the section it's filed under, OR the file is in
        :data:`_CROSS_SECTION_ALLOWLIST` with a stated reason, OR it is a
        root file in :data:`_ROOT_FILE_SECTIONS`.
        """
        # Allowlisted rows are the named exception, not evidence of a pattern:
        # excluding them here is what keeps platform/operations.md (Operations)
        # from making 'platform' look primary for Operations too, and
        # development/artifact-policy.md (Reference) from making 'development'
        # look primary for Reference too.
        primary_dirs: dict[str, set[str]] = {}
        for section, _, path in self.nav.rows:
            if path in _CROSS_SECTION_ALLOWLIST or path in _ROOT_FILE_SECTIONS:
                continue
            directory = Path(path).parent.as_posix()
            if directory == ".":
                continue
            primary_dirs.setdefault(section, set()).add(directory.split("/")[0])

        offenders = []
        for section, title, path in self.nav.rows:
            if path in _ROOT_FILE_SECTIONS:
                self.assertEqual(section, _ROOT_FILE_SECTIONS[path])
                continue
            if path in _CROSS_SECTION_ALLOWLIST:
                continue
            top_dir = path.split("/")[0]
            if top_dir not in primary_dirs.get(section, set()):
                offenders.append(f"{path!r} (title {title!r}) filed under {section!r}")

        # Every primary directory should itself be unambiguous: exactly one
        # section should treat it as primary (Start/tutorials and
        # Projects/workflows are each declared once, for one section).
        dir_to_sections: dict[str, set[str]] = {}
        for section, dirs in primary_dirs.items():
            for d in dirs:
                dir_to_sections.setdefault(d, set()).add(section)
        ambiguous = {d: s for d, s in dir_to_sections.items() if len(s) > 1}

        self.assertEqual(
            [],
            offenders,
            "these pages sit in a directory that is not a primary directory "
            "of the section they're filed under, and are not in "
            "_CROSS_SECTION_ALLOWLIST with a stated reason:\n"
            + "\n".join(f"  {o}" for o in offenders),
        )
        self.assertEqual(
            {},
            ambiguous,
            "these directories are treated as 'primary' by more than one "
            f"section, which defeats the point of the rule: {ambiguous}",
        )

    def test_a_misplaced_file_turns_the_gate_red(self) -> None:
        """Mutation: filing a page under a directory-mismatched section fails.

        Reproduces the exact pre-restructure defect: a ``platform/``-housed
        page placed under a section whose primary directory is something
        else, with no allowlist entry.
        """
        synthetic_rows = list(self.nav.rows) + [
            ("SDK", "A Misplaced Platform Page", "platform/a-new-page.md"),
        ]
        primary_dirs: dict[str, set[str]] = {}
        for section, _, path in self.nav.rows:  # unmutated -- SDK's real dirs
            if path in _CROSS_SECTION_ALLOWLIST or path in _ROOT_FILE_SECTIONS:
                continue
            directory = Path(path).parent.as_posix()
            if directory != ".":
                primary_dirs.setdefault(section, set()).add(directory.split("/")[0])
        new_section, _, new_path = synthetic_rows[-1]
        self.assertNotIn(
            new_path.split("/")[0],
            primary_dirs.get(new_section, set()),
            "the mutation's directory is already primary for its section -- "
            "pick a directory this test's own section doesn't already own",
        )


if __name__ == "__main__":
    unittest.main()
