"""Gate for the documentation instruction ledger in ``tools/``.

``tools/check_doc_instructions.py`` extracts every fenced code block in
``docs/**/*.md`` plus ``README.md`` and checks the tracked ledger
``docs/development/instruction-ledger.json`` against them. This module wires that
checker into pytest.

Why a ledger and not "run the docs"
-----------------------------------
Measured: **354 fenced blocks across 78 documents**. Only 162 of them are of a
runnable class at all -- 150 are illustrative, 24 exceed ten minutes, 14 need a
runtime beyond the Python environment and 4 delete state or mutate a remote. A
gate that executed the corpus would be red forever; a gate that executed none of
it would prove nothing. So each block is classified once, by hand, and the
classification is pinned. This module makes the pin bite.

(The tree walks 85 markdown documents; 7 are git-ignored and therefore outside
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

Wave 3 closes the milestone and adds the assertions that keep it closed. The
ledger now carries a verdict for every instruction, merged from the three
wave-2 execution fragments, so the gate stops asking only "is it classified?"
and starts asking "was it answered?":

* :meth:`InstructionLedgerTests.test_no_instruction_is_unverified` is R14.
  All 162 runnable blocks must resolve to a verdict that is not ``UNVERIFIED``.
  A ``RUNNABLE-SEQUENCE`` member leaves ``verdict`` null on purpose -- the chain
  is the unit that can be run -- so it is resolved *through* its sequence rather
  than skipped. A null is a pointer here, never a hiding place.
* :meth:`InstructionLedgerTests.test_documented_verdicts_state_why_they_were_not_executed`
  is the other half: a ``DOCUMENTED`` verdict is a decision not to run
  something, and one with no reason is an opt-out. Note this is broader than
  the checker's own rationale rule, which asks only the four documented
  *classes*; two runnable blocks were deliberately not run and would slip
  through there.
* :meth:`InstructionLedgerTests.test_every_command_bearing_document_has_a_verification_owner`
  replaces "the unowned set has not changed" with the stronger claim that drove
  the phase: no document carrying commands may sit outside every family. Wave 1
  found four unowned documents, two of them carrying commands; rather than pin
  the gap, ``FAMILY_PREFIXES`` was amended to claim them, so ownership has
  exactly one source and cannot drift from a second one.
* :meth:`InstructionLedgerTests.test_the_flagship_deferral_is_recorded` pins the
  largest deferral in the corpus -- the ~6 h ``ev_hosting_flex`` run, instructed
  by 15 blocks and deliberately not executed -- so it stays a recorded decision.

Each of those three rules has a mutation test that watches it go red:
:meth:`InstructionLedgerTests.test_a_flipped_verdict_turns_the_gate_red`,
:meth:`InstructionLedgerTests.test_an_emptied_rationale_turns_the_gate_red` and
:meth:`InstructionLedgerTests.test_an_unowned_command_document_turns_the_gate_red`.
Each is watched green first, so the red is attributable to the mutation.

Plus four structural pins:
:meth:`InstructionLedgerTests.test_families_are_disjoint_and_cover_the_split`;
:meth:`InstructionLedgerTests.test_no_corpus_document_is_left_unowned` -- the
family split is what wave-2 execution is partitioned by, so a document outside
every family would be verified by nobody;
:meth:`InstructionLedgerTests.test_excluded_documents_are_the_git_ignored_ones`,
which keeps the corpus identical on a developer's tree and in CI; and
:meth:`InstructionLedgerTests.test_classification_was_reviewed_not_generated`,
which asserts the ledger disagrees with the structural suggester often enough to
prove a human read the blocks.

This module reads exactly two things: the corpus (tracked markdown) and the
tracked ledger. It never reads ``.planning/``.
"""

from __future__ import annotations

import copy
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
# git-ignored document is outside the corpus, so both see the same 78 documents
# and the same 354 blocks. Each floor sits below the measured figure but far
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
# everywhere, nobody read the blocks -- measured 124 of 354 disagree.
_MIN_REVIEW_OVERRIDES = 60

# Documents no family claims. This is a REAL FINDING about the documentation
# tree, not a bug in the checker: the phase's family split covers
# getting-started/reference/README, platform/tutorials/flexibility/workflows/
# projects/sdk/concepts and development, and these four sit outside all three.
# The documents the ORIGINAL three-family split left unowned. Three carried
# blocks (14 in total, 3 of a runnable class), so real instructions would have
# been verified by nobody. Kept only as the historical record of what the gap
# was: FAMILY_PREFIXES was amended to claim them, and
# ``test_no_corpus_document_is_left_unowned`` now asserts the set is EMPTY.
_ONCE_UNASSIGNED: tuple[str, ...] = (
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


#: Fence languages that carry a command a reader is expected to run. Defined
#: here rather than imported so the ownership rule below is the *test's* claim
#: about what "a document carrying instructions" means, not a private detail of
#: the suggester that could be narrowed without this gate noticing.
_COMMAND_FENCES: frozenset[str] = frozenset(
    {"bash", "sh", "shell", "console", "zsh", "python", "py"}
)


def _effective_verdicts(ledger: dict[str, Any]) -> dict[str, str | None]:
    """Return the verdict that actually answers for each runnable instruction.

    A ``RUNNABLE-INDEPENDENT`` block answers for itself. A ``RUNNABLE-SEQUENCE``
    block deliberately leaves ``verdict`` null -- running member 5 of a chain
    alone is meaningless, so the chain owns the single verdict -- and is
    resolved **through** its sequence here. That resolution is the whole point:
    a null must never be a place a verdict can hide, so this maps the member
    onto the sequence's verdict rather than skipping it.
    """
    blocks = ledger["blocks"]
    sequences = ledger["sequences"]
    resolved: dict[str, str | None] = {}
    for key, entry in sorted(blocks.items()):
        if entry["class"] == checker.RUNNABLE_INDEPENDENT:
            resolved[key] = entry["verdict"]
        elif entry["class"] == checker.RUNNABLE_SEQUENCE:
            owner = sequences.get(str(entry["sequence"]))
            resolved[key] = owner["verdict"] if owner is not None else None
    return resolved


def _unverified_instructions(ledger: dict[str, Any]) -> list[str]:
    """Return every instruction whose verdict is UNVERIFIED, or absent.

    Covers all three ways an instruction could go unanswered: a block that says
    UNVERIFIED, a sequence that says UNVERIFIED, and a chain member whose null
    resolves to nothing because its sequence is missing.
    """
    offenders = [
        f"{key}: verdict {verdict!r}"
        for key, verdict in _effective_verdicts(ledger).items()
        if verdict is None or verdict == checker.UNVERIFIED
    ]
    offenders += [
        f"{key}: sequence verdict {entry['verdict']!r}"
        for key, entry in sorted(ledger["sequences"].items())
        if entry["verdict"] == checker.UNVERIFIED
    ]
    offenders += [
        f"{key}: block verdict {entry['verdict']!r}"
        for key, entry in sorted(ledger["blocks"].items())
        if entry["verdict"] == checker.UNVERIFIED
    ]
    return sorted(set(offenders))


def _unjustified_documented(ledger: dict[str, Any]) -> list[str]:
    """Return every DOCUMENTED entry that does not say why it was not executed.

    A DOCUMENTED verdict is a decision *not* to run something, and a decision
    with no stated reason is an opt-out wearing a verdict's clothes. This is
    broader than the checker's own rule, which asks for a rationale from the
    four documented *classes*: a ``RUNNABLE-INDEPENDENT`` block that was
    deliberately not run carries a runnable class and would slip through there.
    """
    offenders = [
        f"blocks/{key}"
        for key, entry in sorted(ledger["blocks"].items())
        if entry["verdict"] == checker.DOCUMENTED
        and not str(entry["rationale"] or "").strip()
    ]
    offenders += [
        f"sequences/{key}"
        for key, entry in sorted(ledger["sequences"].items())
        if entry["verdict"] == checker.DOCUMENTED
        and not str(entry["rationale"] or "").strip()
    ]
    return offenders


def _ownerless_command_documents(root: Path, ledger: dict[str, Any]) -> list[str]:
    """Return corpus documents carrying commands that no family verified.

    Ownership is what wave-2 execution was partitioned by, so a document with
    runnable-looking blocks and no owner goes unverified in silence. A document
    is owned when :func:`checker.family_of` claims it -- ``FAMILY_PREFIXES`` is
    the single source of ownership, so there is no override layer to drift.
    """
    del ledger  # ownership lives in the prefix table, not in the ledger
    ownerless: list[str] = []
    for path in checker.document_files(root):
        relative = path.resolve().relative_to(root.resolve()).as_posix()
        blocks = checker.extract_file_blocks(path.read_text(encoding="utf-8"), relative)
        if not any(block.language in _COMMAND_FENCES for block in blocks):
            continue
        if checker.family_of(relative) != checker.UNASSIGNED:
            continue
        ownerless.append(relative)
    return sorted(ownerless)


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

    def test_no_corpus_document_is_left_unowned(self) -> None:
        """Every corpus document belongs to exactly one verification family.

        Wave 1 found the original three-family split left four documents
        unowned, three of which carried real instruction blocks -- they would
        have been verified by nobody. The split was amended rather than the
        gap pinned, so the assertion is now the strong one: *no* document is
        unowned. A new document under a directory no family claims fails here,
        and the remedy is to extend ``FAMILY_PREFIXES`` -- which is also what
        assigns its blocks to an executor.
        """
        self.assertEqual(
            [],
            list(checker.unassigned_files(_REPO_ROOT)),
            "these documents belong to no verification family, so nothing "
            "would execute their instructions. Extend FAMILY_PREFIXES in "
            "tools/check_doc_instructions.py to give each one an owner",
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

    # -- wave 3: the close-out assertions ---------------------------------
    def test_no_instruction_is_unverified(self) -> None:
        """R14. Every instruction in the corpus carries an answered verdict."""
        offenders = _unverified_instructions(self.result.ledger)
        self.assertEqual(
            [],
            offenders,
            "these instructions carry no verdict. Every one of the 162 "
            "runnable blocks must resolve to an evidenced verdict -- directly "
            "for RUNNABLE-INDEPENDENT, through its sequence for "
            "RUNNABLE-SEQUENCE -- and no entry anywhere may say UNVERIFIED:\n"
            + "\n".join(offenders),
        )

    def test_a_flipped_verdict_turns_the_gate_red(self) -> None:
        """Mutation: flipping any verdict to UNVERIFIED must be named, not missed.

        Run against a copy of the *real* ledger, and watched green first, so the
        red is attributable to the mutation. Both halves of the resolution are
        mutated: a block that answers for itself, and a sequence that answers
        for its members -- because a rule that only checked the first would let
        74 chain members go quietly unanswered behind their nulls.
        """
        ledger = copy.deepcopy(self.result.ledger)
        self.assertEqual([], _unverified_instructions(ledger))

        block_key = "docs/development/artifact-policy.md#0"
        ledger["blocks"][block_key]["verdict"] = checker.UNVERIFIED
        self.assertIn(
            f"{block_key}: block verdict 'UNVERIFIED'",
            _unverified_instructions(ledger),
        )

        ledger = copy.deepcopy(self.result.ledger)
        sequence_key = "docs/getting-started/quickstart.md#seq0"
        members = ledger["sequences"][sequence_key]["members"]
        ledger["sequences"][sequence_key]["verdict"] = checker.UNVERIFIED
        offenders = _unverified_instructions(ledger)
        self.assertIn(f"{sequence_key}: sequence verdict 'UNVERIFIED'", offenders)
        for ordinal in members:
            with self.subTest(member=ordinal):
                self.assertIn(
                    f"docs/getting-started/quickstart.md#{ordinal}: "
                    f"verdict 'UNVERIFIED'",
                    offenders,
                    "a chain member must inherit its sequence's UNVERIFIED "
                    "rather than pass on a null",
                )

    def test_documented_verdicts_state_why_they_were_not_executed(self) -> None:
        """A decision not to run something must carry its reason.

        The deferral classes -- LONG-RUNNING, DESTRUCTIVE, ENV-DEPENDENT -- may
        legitimately end either way: 12 of the 14 ENV-DEPENDENT blocks were
        actually executed and carry an execution verdict, and demanding a
        deferral rationale from those would be wrong. What may never happen is
        an entry that is neither executed nor justified.
        """
        offenders = _unjustified_documented(self.result.ledger)
        self.assertEqual(
            [],
            offenders,
            "these entries were documented rather than executed but give no "
            "reason, which is an opt-out from verification rather than a "
            "decision about it:\n" + "\n".join(offenders),
        )

    def test_an_emptied_rationale_turns_the_gate_red(self) -> None:
        """Mutation: blanking a DOCUMENTED entry's rationale must be named."""
        ledger = copy.deepcopy(self.result.ledger)
        self.assertEqual([], _unjustified_documented(ledger))

        block_key = "docs/getting-started/reproducibility.md#2"
        self.assertEqual(checker.DOCUMENTED, ledger["blocks"][block_key]["verdict"])
        ledger["blocks"][block_key]["rationale"] = "   "
        self.assertEqual([f"blocks/{block_key}"], _unjustified_documented(ledger))

        ledger = copy.deepcopy(self.result.ledger)
        # docs/development/public-api.md -> docs/sdk/public-api.md, 2026-08-13
        # information-architecture restructure.
        sequence_key = "docs/sdk/public-api.md#seq1"
        self.assertEqual(
            checker.DOCUMENTED, ledger["sequences"][sequence_key]["verdict"]
        )
        ledger["sequences"][sequence_key]["rationale"] = ""
        self.assertEqual([f"sequences/{sequence_key}"], _unjustified_documented(ledger))

    def test_every_command_bearing_document_has_a_verification_owner(self) -> None:
        """No document carrying commands may sit outside every family.

        This is the behavioural half of
        :meth:`test_no_corpus_document_is_left_unowned`: that one asserts the
        prefix table covers the corpus, this one asserts the consequence that
        actually matters -- no document carrying commands escapes execution.
        ``docs/index.md`` and (before the 2026-08-13 restructure moved it to
        ``docs/reference/semantic-graph.md``, where the ``getting-started``
        family's own prefix now claims it without a ruling)
        ``docs/semantic-layer/semantic-graph.md`` were the two real cases that
        needed one; both were claimed by the platform family via a literal
        ``FAMILY_PREFIXES`` entry and executed there. A genuinely new unowned
        command document fails here.
        """
        ownerless = _ownerless_command_documents(_REPO_ROOT, self.result.ledger)
        self.assertEqual(
            [],
            ownerless,
            "these documents carry runnable-looking blocks that no verification "
            "family claims, so their instructions would go unverified in "
            "silence. Extend FAMILY_PREFIXES in "
            "tools/check_doc_instructions.py to give each one an owner:\n"
            + "\n".join(ownerless),
        )

    def test_an_unowned_command_document_turns_the_gate_red(self) -> None:
        """Mutation: a new command document under no family prefix must fail.

        Built as a synthetic corpus so the result depends on the rule alone,
        and watched green first. The unowned directory is a name no entry of
        ``FAMILY_PREFIXES`` claims -- deliberately not a real one, since the
        prefix table now covers every directory the corpus actually carries.
        """
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            owned = root / "docs" / "getting-started"
            owned.mkdir(parents=True)
            (owned / "note.md").write_text(_SYNTHETIC_DOC, encoding="utf-8")
            unowned = root / "docs" / "unclaimed-area"
            unowned.mkdir(parents=True)
            prose = unowned / "prose-only.md"
            prose.write_text("# Prose\n\n```text\nnot a command\n```\n", "utf-8")
            ledger: dict[str, Any] = {}

            self.assertEqual(
                [],
                _ownerless_command_documents(root, ledger),
                "an owned command document and an unowned prose-only document "
                "must both pass; only commands need an owner",
            )

            new = unowned / "runbook.md"
            new.write_text("# New\n\n```bash\nuv run gridalyn doctor\n```\n", "utf-8")
            self.assertEqual(
                ["docs/unclaimed-area/runbook.md"],
                _ownerless_command_documents(root, ledger),
            )

            # The only remedy is ownership in the prefix table. There is no
            # ledger override to reach for -- the Phase 7 ruling that claimed
            # docs/index.md and docs/semantic-layer/ was applied there, so
            # ownership has exactly one source and cannot drift from it.
            moved = owned / "runbook.md"
            new.rename(moved)
            self.assertEqual([], _ownerless_command_documents(root, ledger))

    def test_the_flagship_deferral_is_recorded(self) -> None:
        """The ~6 h study run is a recorded decision, not a silent omission.

        The blocks that instruct it are the largest single deferral in the
        corpus. Pinning the decision here means dropping it, or quietly letting
        one of the blocks fall out of the LONG-RUNNING class, fails the gate
        rather than reading as verified.
        """
        deferral = self.result.ledger["deferrals"]["ev_hosting_flex-flagship-run"]
        self.assertTrue(str(deferral["reason"]).strip(), "the deferral gives no reason")
        blocks = self.result.ledger["blocks"]
        named = list(deferral["blocks"])
        self.assertNotEqual([], named)
        for key in named:
            with self.subTest(block=key):
                self.assertIn(key, blocks, "the deferral names a block that is gone")
                self.assertEqual(checker.LONG_RUNNING, blocks[key]["class"])
                self.assertEqual(checker.DOCUMENTED, blocks[key]["verdict"])
                self.assertTrue(str(blocks[key]["rationale"]).strip())
        instructing = sorted(
            block.key
            for block in self.result.blocks
            if blocks[block.key]["class"] == checker.LONG_RUNNING
            and "ev_hosting_flex" in block.content
        )
        self.assertEqual(
            instructing,
            sorted(named),
            "the recorded deferral must name every LONG-RUNNING block that "
            "instructs the flagship run, or one of them is deferred without "
            "the decision covering it",
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
        # Wave 3 adds three header keys and no per-record field. The block and
        # sequence records still carry exactly the fields the checker documents,
        # which is what keeps `schema_version` at 1.0: the additions are header
        # metadata the checker ignores, not a change to the records it reads.
        for header in ("merged_on", "deferrals"):
            with self.subTest(header=header):
                self.assertIn(header, raw)
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
            + "\ndoc instruction unowned documents: none ("
            + f"{len(_ONCE_UNASSIGNED)} were, before the split was amended)"
        )
        self.assertGreater(sum(counts.values()), 0)


if __name__ == "__main__":
    unittest.main()
