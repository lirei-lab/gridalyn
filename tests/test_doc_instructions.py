"""Gate for the documentation instruction ledger in ``tools/``.

``tools/check_doc_instructions.py`` extracts every fenced code block in
``docs/**/*.md`` plus ``README.md`` and checks the tracked ledger
``docs/development/instruction-ledger.json`` against them. This module wires that
checker into pytest.

Why a ledger and not "run the docs"
-----------------------------------
Measured: **350 fenced blocks across 77 documents**. Only 159 of them are of a
runnable class at all -- 150 are illustrative, 23 exceed ten minutes, 14 need a
runtime beyond the Python environment and 4 delete state or mutate a remote. A
gate that executed the corpus would be red forever; a gate that executed none of
it would prove nothing. So each block is classified once, by hand, and the
classification is pinned. This module makes the pin bite.

(The tree walks 84 markdown documents; 7 are git-ignored and therefore outside
the corpus -- see the CI-parity pin listed below.)

The cases
---------
* :meth:`InstructionLedgerTests.test_every_block_is_classified` is the gate. A
  new fenced block has no entry, so it fails here until someone reads it and
  classifies it.
* :meth:`InstructionLedgerTests.test_no_classified_block_has_drifted` is the
  other half. Editing a classified block changes its ``sha1``, and the entry's
  verdict was evidence about text that no longer exists, so the entry goes
  stale rather than silently continuing to vouch for the new content.
* :meth:`InstructionLedgerTests.test_no_orphaned_or_invalid_entries` covers the
  reverse direction and the schema: an entry naming a deleted block, a class or
  verdict outside the declared sets, a documented class with an empty rationale,
  a sequence whose members disagree with the blocks that name it.
* :meth:`InstructionLedgerTests.test_ledger_is_not_vacuous` is the non-vacuity
  guard: a checker that extracted nothing would report "every block is
  classified" while proving nothing, so the corpus size, the runnable population
  and each family carry a floor.
* :meth:`InstructionLedgerTests.test_emptied_corpus_trips_the_floors` mutates the
  corpus to empty and asserts those floors actually fire. A floor never shown to
  fail is decoration.
* :meth:`InstructionLedgerTests.test_synthetic_corpus_mutations` is the pair of
  load-bearing mutations, run against a synthetic corpus so the result depends on
  the checker alone: **adding** a fenced block turns the gate red naming it, and
  **editing** a classified block turns it red on the hash. Both are watched green
  first, so the red is attributable to the mutation.

Plus four structural pins:
:meth:`InstructionLedgerTests.test_families_are_disjoint_and_cover_the_split`;
:meth:`InstructionLedgerTests.test_unassigned_documents_are_the_known_four` --
the family split is what wave-2 execution is partitioned by, so a document
outside every family is a finding, pinned here rather than folded into a
neighbour;
:meth:`InstructionLedgerTests.test_excluded_documents_are_the_git_ignored_ones`,
which keeps the corpus identical on a developer's tree and in CI; and
:meth:`InstructionLedgerTests.test_classification_was_reviewed_not_generated`,
which asserts the ledger disagrees with the structural suggester often enough to
prove a human read the blocks.

This module reads exactly two things: the corpus (tracked markdown) and the
tracked ledger. It never reads ``.planning/``.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CHECKER_PATH = _REPO_ROOT / "tools" / "check_doc_instructions.py"


def _load_checker() -> ModuleType:
    """Import ``tools/check_doc_instructions.py`` without mutating ``sys.path``.

    The module is registered in ``sys.modules`` before execution because
    ``@dataclass`` resolves ``cls.__module__`` through it.
    """
    spec = importlib.util.spec_from_file_location(
        "check_doc_instructions", _CHECKER_PATH
    )
    if spec is None or spec.loader is None:  # pragma: no cover - unreachable
        raise ImportError(f"cannot load {_CHECKER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


# Non-vacuity floors.
#
# Set from what a CLEAN CHECKOUT carries, not from this working tree: every
# git-ignored document is outside the corpus, so both see the same 77 documents
# and the same 350 blocks. Each floor sits below the measured figure but far
# above a token 1: a partially blind extractor -- one that only recognised ```
# and not ~~~, say -- also reports "everything is classified".
_MIN_BLOCKS = 300
_MIN_FILES = 70
_MIN_RUNNABLE = 100
_MIN_SEQUENCES = 10
# Per-family runnable floors. Wave 2 splits execution three ways and sizes each
# leg against these numbers, so a family that silently emptied would hand an
# executor nothing to do while still passing the total floor above.
_MIN_RUNNABLE_PER_FAMILY: dict[str, int] = {
    "getting-started": 30,
    "platform": 50,
    "development": 20,
}
# The structural suggester is a first pass. If the ledger agreed with it
# everywhere, nobody read the blocks -- measured 124 of 350 disagree.
_MIN_REVIEW_OVERRIDES = 60

# Documents no family claims. This is a REAL FINDING about the documentation
# tree, not a bug in the checker: the phase's family split covers
# getting-started/reference/README, platform/tutorials/flexibility/workflows/
# projects/sdk/concepts and development, and these four sit outside all three.
# Three of them carry blocks (14 in total, 3 of a runnable class), so leaving
# them unowned would let real instructions go unverified in silence. Pinned so a
# NEW unowned document fails here rather than joining them quietly.
_KNOWN_UNASSIGNED: tuple[str, ...] = (
    "docs/applications/reports.md",
    "docs/index.md",
    "docs/semantic-layer/falkordb.md",
    "docs/semantic-layer/semantic-graph.md",
)

_SYNTHETIC_DOC = """# Synthetic

Prose that is not a block.

```bash
uv run gridalyn --help
```

More prose.

```text
an output sample
```
"""

_ADDED_BLOCK = """
An undocumented addition.

```bash
uv run gridalyn doctor
```
"""


def _build_synthetic_corpus(root: Path) -> Path:
    """Create a minimal corpus of one document, and return its path."""
    docs = root / "docs" / "getting-started"
    docs.mkdir(parents=True, exist_ok=True)
    document = docs / "note.md"
    document.write_text(_SYNTHETIC_DOC, encoding="utf-8")
    return document


def _classify_all(root: Path, ledger_path: Path) -> None:
    """Write a ledger that covers every block of a synthetic corpus."""
    ledger, _added = checker.merge_suggestions(
        checker.load_ledger(ledger_path), checker.extract_blocks(root)
    )
    checker.write_ledger(ledger_path, ledger)


def _floor_failures(result: Any) -> list[str]:
    """Return one message per non-vacuity floor the audit fails to clear.

    Shared by the guard and by its own mutation test, so the floors are
    exercised in both directions rather than only in the passing one.
    """
    failures: list[str] = []
    total = len(result.blocks)
    if total < _MIN_BLOCKS:
        failures.append(f"only {total} blocks extracted (floor {_MIN_BLOCKS})")
    if result.files_scanned < _MIN_FILES:
        failures.append(
            f"only {result.files_scanned} documents scanned (floor {_MIN_FILES})"
        )
    counts = result.class_counts()
    runnable = sum(counts[label] for label in checker.RUNNABLE_CLASSES)
    if runnable < _MIN_RUNNABLE:
        failures.append(
            f"only {runnable} blocks of a runnable class (floor {_MIN_RUNNABLE})"
        )
    if len(result.sequences()) < _MIN_SEQUENCES:
        failures.append(
            f"only {len(result.sequences())} sequences (floor {_MIN_SEQUENCES})"
        )
    per_family = result.runnable_by_family()
    for family, floor in sorted(_MIN_RUNNABLE_PER_FAMILY.items()):
        if per_family[family] < floor:
            failures.append(
                f"family {family} carries only {per_family[family]} runnable "
                f"blocks (floor {floor})"
            )
    return failures


class InstructionLedgerTests(unittest.TestCase):
    """Enforce and prove the documentation instruction-ledger contract."""

    def setUp(self) -> None:
        """Audit the repository once per test."""
        self.result = checker.audit(_REPO_ROOT)

    # -- the gate ---------------------------------------------------------
    def test_every_block_is_classified(self) -> None:
        """No fenced block may exist without a reviewed ledger entry."""
        offenders = [finding.located() for finding in self.result.unclassified]
        self.assertEqual(
            [],
            offenders,
            "a fenced code block carries no entry in "
            f"{checker.LEDGER_REL}. Read the block, decide its class from "
            f"{', '.join(checker.CLASSES)}, and record it -- "
            "`python tools/check_doc_instructions.py --suggest` drafts the "
            "entries, but the class is a human judgement:\n" + "\n".join(offenders),
        )

    def test_no_classified_block_has_drifted(self) -> None:
        """An edited block invalidates its entry rather than silently keeping it."""
        offenders = [finding.located() for finding in self.result.stale]
        self.assertEqual(
            [],
            offenders,
            "a classified block's content changed, so its entry vouches for text "
            "that no longer exists. Re-read the block, update 'sha1', and "
            "re-evidence any verdict the edit invalidated:\n" + "\n".join(offenders),
        )

    def test_no_orphaned_or_invalid_entries(self) -> None:
        """Entries must name a live block and satisfy the schema."""
        offenders = [
            finding.located()
            for finding in tuple(self.result.orphaned) + tuple(self.result.invalid)
        ]
        self.assertEqual(
            [],
            offenders,
            "the ledger disagrees with the corpus or with its own schema; a "
            "standing classification over a block that no longer exists is a "
            "silent permission:\n" + "\n".join(offenders),
        )

    def test_checker_cli_agrees_with_the_gate(self) -> None:
        """The CLI a developer runs must return 0 exactly when the gate is green."""
        self.assertEqual(
            0, checker.main([]), [f.located() for f in self.result.findings]
        )

    # -- non-vacuity ------------------------------------------------------
    def test_ledger_is_not_vacuous(self) -> None:
        """The corpus, the runnable population and each family clear their floors."""
        failures = _floor_failures(self.result)
        self.assertEqual(
            [],
            failures,
            "the checker found too little to be trusted; an extractor that finds "
            "nothing reports that every block is classified and proves nothing:\n"
            + "\n".join(failures),
        )

    def test_emptied_corpus_trips_the_floors(self) -> None:
        """Mutation: an empty corpus must fail the floors, not pass them."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            empty = checker.audit(root, root / "ledger.json")
            self.assertEqual(0, len(empty.blocks))
            self.assertNotEqual(
                [],
                _floor_failures(empty),
                "an empty corpus cleared every non-vacuity floor, so the floors "
                "would not catch a broken extractor",
            )

    # -- the load-bearing mutations ---------------------------------------
    def test_synthetic_corpus_mutations(self) -> None:
        """Adding a block goes red by name; editing one goes red on the hash.

        Run against a synthetic corpus rather than the live docs so the result
        depends on the checker alone, and watched green first so the red is
        attributable to the mutation and not to a pre-existing failure.
        """
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ledger_path = root / "ledger.json"
            document = _build_synthetic_corpus(root)
            _classify_all(root, ledger_path)

            baseline = checker.audit(root, ledger_path)
            self.assertEqual(2, len(baseline.blocks))
            self.assertEqual(
                (), baseline.findings, [f.located() for f in baseline.findings]
            )
            self.assertEqual(
                0, checker.main(["--root", str(root), "--ledger", str(ledger_path)])
            )

            # Mutation A -- a new fenced block appears.
            document.write_text(_SYNTHETIC_DOC + _ADDED_BLOCK, encoding="utf-8")
            added = checker.audit(root, ledger_path)
            self.assertEqual(3, len(added.blocks))
            self.assertEqual(
                ["docs/getting-started/note.md#2"],
                [finding.key for finding in added.unclassified],
                [f.located() for f in added.findings],
            )
            self.assertEqual(
                1, checker.main(["--root", str(root), "--ledger", str(ledger_path)])
            )

            # Mutation B -- a classified block's content changes.
            document.write_text(
                _SYNTHETIC_DOC.replace("gridalyn --help", "gridalyn doctor"),
                encoding="utf-8",
            )
            edited = checker.audit(root, ledger_path)
            self.assertEqual(2, len(edited.blocks))
            self.assertEqual((), edited.unclassified, "mutation B must not add a block")
            self.assertEqual(
                ["docs/getting-started/note.md#0"],
                [finding.key for finding in edited.stale],
                [f.located() for f in edited.findings],
            )
            self.assertEqual(
                1, checker.main(["--root", str(root), "--ledger", str(ledger_path)])
            )

            # Mutation C -- a block is deleted; its entry must not linger.
            document.write_text("# Synthetic\n\nNo blocks at all.\n", encoding="utf-8")
            emptied = checker.audit(root, ledger_path)
            self.assertEqual(
                ["docs/getting-started/note.md#0", "docs/getting-started/note.md#1"],
                sorted(finding.key for finding in emptied.orphaned),
                [f.located() for f in emptied.findings],
            )

    # -- structural pins --------------------------------------------------
    def test_families_are_disjoint_and_cover_the_split(self) -> None:
        """No document may be claimed by two families, and the split is by prefix."""
        prefixes: list[tuple[str, str]] = [
            (name, prefix)
            for name, group in checker.FAMILY_PREFIXES
            for prefix in group
        ]
        for name, prefix in prefixes:
            for other_name, other_prefix in prefixes:
                if name == other_name or prefix == other_prefix:
                    continue
                with self.subTest(prefix=prefix, other=other_prefix):
                    self.assertFalse(
                        prefix.startswith(other_prefix),
                        f"{prefix} (family {name}) sits inside {other_prefix} "
                        f"(family {other_name}); the split must be disjoint",
                    )
        counts = self.result.family_counts()
        self.assertEqual(
            len(self.result.blocks),
            sum(counts.values()),
            "every block must land in exactly one family bucket",
        )

    def test_unassigned_documents_are_the_known_four(self) -> None:
        """A document outside every family is a finding, not a default.

        Three of the four carry real instruction blocks, so a new unowned
        document would hand wave-2 execution nothing to run them under. Adding
        one must fail here.
        """
        self.assertEqual(
            list(_KNOWN_UNASSIGNED),
            list(checker.unassigned_files(_REPO_ROOT)),
            "the set of documents no family claims changed. Either extend "
            "FAMILY_PREFIXES in tools/check_doc_instructions.py so the new "
            "document is owned and verified, or pin it here with the reason it "
            "is deliberately unowned",
        )

    def test_excluded_documents_are_the_git_ignored_ones(self) -> None:
        """The corpus must be exactly what a clean checkout carries.

        Ledger coverage is exact in both directions, so a document present here
        and absent in CI is fatal: its entries read "unclassified" on one machine
        and "orphaned" on the other. The rule is therefore mechanical -- the
        corpus is every walked document git does **not** ignore -- and it is
        checked both ways:

        * every path in ``EXCLUDED_DOCS`` really is git-ignored, so nothing is
          quietly excused from classification;
        * no document still in the corpus is git-ignored, so a newly-ignored
          document fails here rather than turning CI red later.
        """
        ignored = self._git_ignored(
            list(checker.EXCLUDED_DOCS)
            + [
                path.resolve().relative_to(_REPO_ROOT).as_posix()
                for path in checker.document_files(_REPO_ROOT)
            ]
        )
        not_really_ignored = sorted(set(checker.EXCLUDED_DOCS) - ignored)
        self.assertEqual(
            [],
            not_really_ignored,
            "these documents are excluded from the corpus but git does NOT "
            "ignore them, so a clean checkout has them and their blocks go "
            "unclassified. Remove them from EXCLUDED_DOCS and classify their "
            "blocks:\n" + "\n".join(not_really_ignored),
        )
        wrongly_included = sorted(
            ignored - set(checker.EXCLUDED_DOCS),
        )
        self.assertEqual(
            [],
            wrongly_included,
            "these documents are in the corpus but git ignores them, so CI does "
            "not have them and their ledger entries would read as orphaned "
            "there. Add them to EXCLUDED_DOCS in "
            "tools/check_doc_instructions.py and drop their entries:\n"
            + "\n".join(wrongly_included),
        )

    @staticmethod
    def _git_ignored(paths: list[str]) -> set[str]:
        """Return which of ``paths`` git ignores, via ``git check-ignore``.

        Returns:
            The ignored subset. Exit status 1 means "none matched", which is a
            legitimate answer, not an error.

        Raises:
            unittest.SkipTest: If ``git`` is unavailable or this is not a
                repository -- an installed-source-archive run has no index to
                ask, and guessing would be worse than skipping.
        """
        try:
            completed = subprocess.run(
                ["git", "check-ignore", "--stdin"],
                cwd=_REPO_ROOT,
                input="\n".join(paths),
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as error:  # pragma: no cover - git is present in CI
            raise unittest.SkipTest(f"git unavailable: {error}") from error
        if completed.returncode not in (0, 1):  # pragma: no cover - not a repo
            raise unittest.SkipTest(
                f"git check-ignore failed ({completed.returncode}): "
                f"{completed.stderr.strip()}"
            )
        return {line.strip() for line in completed.stdout.splitlines() if line.strip()}

    def test_classification_was_reviewed_not_generated(self) -> None:
        """The ledger must disagree with the suggester, or nobody read the blocks.

        The structural suggester looks at the fence language and at command
        names; it cannot tell ``uv run gridalyn verify projects/<project>`` (a
        pseudo-command) from a real one, nor a tutorial chain from a standalone
        command. A ledger that matched it everywhere would be machine output
        wearing a review's clothes.
        """
        entries = self.result.ledger["blocks"]
        overrides = [
            key
            for key, entry in sorted(entries.items())
            if entry["auto"] != entry["class"]
        ]
        self.assertGreaterEqual(
            len(overrides),
            _MIN_REVIEW_OVERRIDES,
            f"only {len(overrides)} of {len(entries)} entries disagree with the "
            f"structural suggestion (floor {_MIN_REVIEW_OVERRIDES}); that reads "
            "like a generated ledger rather than a reviewed one",
        )

    def test_documented_classes_carry_a_rationale(self) -> None:
        """Every non-runnable class says why it is documented rather than executed.

        Wave 3 requires this string to be non-empty at close; asserting it now
        stops a class from being used as a way to opt out of verification without
        stating a reason.
        """
        entries = self.result.ledger["blocks"]
        missing = [
            key
            for key, entry in sorted(entries.items())
            if entry["class"] in checker.DOCUMENTED_CLASSES
            and not str(entry["rationale"]).strip()
        ]
        self.assertEqual(
            [],
            missing,
            "these entries are classified as documented-rather-than-executed but "
            "give no reason:\n" + "\n".join(missing),
        )

    def test_ledger_is_valid_json_with_the_declared_schema(self) -> None:
        """The tracked ledger parses and carries the header wave 3 merges into."""
        raw = json.loads((_REPO_ROOT / checker.LEDGER_REL).read_text(encoding="utf-8"))
        self.assertEqual("1.0", raw["schema_version"])
        self.assertEqual(
            "docs/**/*.md + README.md, minus the git-ignored documents in "
            "EXCLUDED_DOCS",
            raw["corpus"],
        )
        expected = {
            "class",
            "auto",
            "family",
            "file",
            "ordinal",
            "line",
            "language",
            "sha1",
            "sequence",
            "verdict",
            "rationale",
            "evidence",
            "date",
        }
        for key, entry in sorted(raw["blocks"].items()):
            with self.subTest(block=key):
                self.assertEqual(expected, set(entry), key)
        sequence_fields = {
            "file",
            "members",
            "workspace",
            "verdict",
            "rationale",
            "evidence",
            "date",
        }
        for key, entry in sorted(raw["sequences"].items()):
            with self.subTest(sequence=key):
                self.assertEqual(sequence_fields, set(entry), key)

    # -- measurement ------------------------------------------------------
    def test_distribution_is_measured_not_implied(self) -> None:
        """Print the numbers wave 2 sizes its execution against."""
        counts = self.result.class_counts()
        per_family = self.result.runnable_by_family()
        print(
            f"\ndoc instructions: {len(self.result.blocks)} fenced blocks across "
            f"{self.result.files_scanned} documents -- "
            + ", ".join(f"{label} {counts[label]}" for label in checker.CLASSES)
            + f"\ndoc instruction sequences: {len(self.result.sequences())}"
            + "\ndoc instruction runnable-family members: "
            + ", ".join(
                f"{name} {per_family[name]}"
                for name in checker.FAMILIES
                if per_family[name]
            )
            + "\ndoc instruction unowned documents: "
            + ", ".join(_KNOWN_UNASSIGNED)
        )
        self.assertGreater(sum(counts.values()), 0)


if __name__ == "__main__":
    unittest.main()
