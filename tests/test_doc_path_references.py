"""Gate for the documentation path-reference classifier in ``tools/``.

``tools/check_doc_paths.py`` sorts every path reference in the documentation
surface into ``SOURCE`` (must resolve), ``SHORTHAND`` (prefix-relative, correct
as written), ``RUNTIME`` (generated or git-ignored, correct as written) or
``UNCLASSIFIED`` (a hole in the taxonomy). This module wires that classifier
into pytest.

Why a classifier and not an existence check
-------------------------------------------
Measured on a clean ``git archive`` export of ``HEAD``: 519 references, of
which a naive ``Path.exists()`` check flags 279 -- and **276 of those 279 are
written correctly**. An existence check would therefore be ~99% false alarms
and useless as a gate. Only the classification makes the remediation safe.

Five cases:

* :meth:`DocPathReferenceTests.test_no_unwaived_broken_references` is the gate.
  Every stale ``SOURCE`` and every ``UNCLASSIFIED`` reference must appear in
  :data:`_ALLOWLIST`, per reference. There is no tree-level waiver.
* :meth:`DocPathReferenceTests.test_allowlist_entries_still_match` fails when a
  pinned entry stops matching, so a reference that later gets fixed cannot
  leave a silent standing permission behind. Entries whose file is absent from
  the checkout are skipped rather than failed -- ``CLAUDE.md`` and ``AGENTS.md``
  are git-ignored, so CI genuinely does not have them.
* :meth:`DocPathReferenceTests.test_classifier_is_not_vacuous` is the
  non-vacuity guard. A scanner that extracted nothing would report "no stale
  references" while proving nothing, so each class carries a floor.
* :meth:`DocPathReferenceTests.test_emptied_reference_list_trips_the_floor`
  mutates the corpus to empty and asserts those floors actually fire. A floor
  that is never shown to fail is decoration.
* :meth:`DocPathReferenceTests.test_synthetic_tree_mutations` is the pair of
  load-bearing mutations, run against a synthetic repository so they stay
  meaningful no matter what the real docs say: a newly-broken fully-qualified
  source reference must turn the gate **red**, and a runtime-artifact path must
  leave it **green**. The second is the one that matters -- a classifier that
  fails it is just an existence check wearing a costume.

Plus two structural pins:
:meth:`DocPathReferenceTests.test_shorthand_prefixes_are_derived` asserts the
prefix list is computed from the layer packages rather than hardcoded, and
:meth:`DocPathReferenceTests.test_runtime_rule_does_not_touch_the_filesystem`
asserts the ``RUNTIME`` decision is identical for a root that exists and one
that does not -- the property that makes the gate answer the same on a
developer's tree (which has run every study) and in CI (which has not).

The ``UNCLASSIFIED`` count is printed rather than merely bounded, so the
taxonomy's blind spot is a measured number instead of an implied zero.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_CHECKER_PATH = _REPO_ROOT / "tools" / "check_doc_paths.py"


def _load_checker() -> ModuleType:
    """Import ``tools/check_doc_paths.py`` without mutating ``sys.path``.

    The module is registered in ``sys.modules`` before execution because
    ``@dataclass`` resolves ``cls.__module__`` through it.
    """
    spec = importlib.util.spec_from_file_location("check_doc_paths", _CHECKER_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - unreachable
        raise ImportError(f"cannot load {_CHECKER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()


# Non-vacuity floors.
#
# Set from what a **clean checkout** carries, not from this working tree. The
# working tree scans 127 documents because CLAUDE.md, AGENTS.md and the 41
# untracked files under docs/superpowers/ are present; a `git archive HEAD`
# export -- which is what CI checks out -- scans 76 and finds 519 references
# (SOURCE 265, SHORTHAND 34, RUNTIME 219). Floors keyed to the working tree
# would pass locally and fail in CI, which is the failure mode this suite has
# been bitten by before. Each floor sits below the clean-checkout figure but
# far above a token 1: a partially blind extractor -- one that read code spans
# but not link targets, say -- also reports zero stale references.
_MIN_FILES_SCANNED = 60
_MIN_FILES_WITH_REFERENCES = 50
_MIN_TOTAL_REFERENCES = 400
_MIN_PER_CLASS: dict[str, int] = {
    checker.SOURCE: 200,
    checker.SHORTHAND: 25,
    checker.RUNTIME: 150,
}

# Ceiling on the taxonomy's blind spot. Measured: 25 in the working tree, 1 in
# a clean checkout. A number materially above this means the three classes are
# the wrong three, not that the docs got worse.
_MAX_UNCLASSIFIED = 30

# There is no tree waiver. There was one -- docs/superpowers/, an untracked tree
# of historical AI-assistant design records whose 68 broken references described
# repo states that had been intentionally superseded. That tree was deleted, so
# the waiver was deleted with it rather than left behind as a standing
# permission over a path that no longer exists. Every exception is now
# per-reference, below.

# Per-reference allowlist for the enforced surface, keyed by
# ``(document, reference)`` -- never by line number, because CLAUDE.md is
# rewritten often enough that a line-keyed entry would rot within a day.
#
# Plan 04-04 empties this dict. Every entry is a real stale reference that this
# plan deliberately did not fix.
_ALLOWLIST: dict[tuple[str, str], str] = {
    (
        "docs/development/report-contract-audit.md",
        "projects/flexibility_cls",
    ): "quoted inside the sentence that states the study was retired 2026-08-03; "
    "the reference is the subject of the correction, not a live link",
    (
        "docs/development/report-contract-audit.md",
        "out_dir/locational_clearing_summary.json",
    ): "`out_dir` is the caller-supplied output-directory argument, not a tracked "
    "directory; the destination only exists once a study has run",
    (
        "docs/development/report-contract-audit.md",
        ".../locational_clearing_verification_report.json",
    ): "deliberately elided runtime destination; the caller chooses `report_path`, "
    "so no fixed prefix exists to resolve it against",
    (
        "CLAUDE.md",
        "operations/settlement",
    ): "extensionless module reference; the file is gridalyn/operations/settlement.py",
    (
        "CLAUDE.md",
        "market/",
    ): "gridalyn/operations/market/ was retired; the successor is clearing/",
    (
        "CLAUDE.md",
        "archive/flexibility_cls",
    ): "a git tag, not a path; the notation is indistinguishable from a directory",
    (
        "CLAUDE.md",
        "recovered/*",
    ): "a git branch glob, not a path",
    (
        "docs/development/cleanup-inventory.md",
        "data/twins/",
    ): "an inventory of paths deliberately removed; being absent is the point",
    (
        "docs/development/cleanup-inventory.md",
        "examples/legacy/",
    ): "an inventory of paths deliberately removed; being absent is the point",
    (
        "docs/development/cleanup-inventory.md",
        "gridalyn/projects/workflows/scripts/sync_dashboard_public_from_digital_twin.py",
    ): "an inventory of paths deliberately removed; being absent is the point",
    (
        "docs/development/cleanup-inventory.md",
        "paper/data/",
    ): "an inventory of paths deliberately removed; being absent is the point",
    (
        "docs/development/cleanup-inventory.md",
        "projects/flexibility_cls",
    ): "the study was retired 2026-08-03 and archived at tag archive/flexibility_cls",
    (
        "docs/development/code-structure-audit.md",
        "gridalyn/api.py",
    ): "an audit of a pre-layering tree; the module never existed under this name",
    (
        "docs/development/release-cleanup-audit.md",
        "examples/legacy/",
    ): "an audit of paths deliberately removed; being absent is the point",
    (
        "docs/development/release-cleanup-audit.md",
        "projects/flexibility_cls",
    ): "the study was retired 2026-08-03 and archived at tag archive/flexibility_cls",
    (
        "docs/getting-started/what-is-gridalyn.md",
        "lirei-lab/gridalyn",
    ): "a GitHub owner/repo slug, not a path",
    (
        "docs/projects/project-model.md",
        "scripts/write_summary_report.py",
    ): "no study ships this stage script; genuinely stale, fixed by Plan 04-04",
}


def _key(finding: Any) -> tuple[str, str]:
    """Return the ``(document, reference)`` key of a finding."""
    return (finding.reference.file, finding.reference.path)


def _fabricate(path: str) -> str:
    """Return an identically-shaped path nothing could have produced.

    Only the file stem is altered: appending to the whole string would change
    the extension, and the extension is itself part of the structural rule, so
    the mutation would be testing the wrong thing.
    """
    trimmed = path.rstrip("/")
    head, _, leaf = trimmed.rpartition("/")
    stem, dot, suffix = leaf.partition(".")
    fabricated = f"{stem}_no_such_29c1f{dot}{suffix}"
    return f"{head}/{fabricated}" if head else fabricated


def _is_waived(key: tuple[str, str]) -> bool:
    """Return True when a finding is covered by the per-reference allowlist."""
    return key in _ALLOWLIST


def _floor_failures(report: object) -> list[str]:
    """Return one message per non-vacuity floor the report fails to clear.

    Shared by the guard and by its own mutation test, so the floors are
    exercised in both directions rather than only in the passing one.
    """
    counts = report.counts()  # type: ignore[attr-defined]
    failures: list[str] = []
    scanned = report.files_scanned  # type: ignore[attr-defined]
    carrying = report.files_with_references  # type: ignore[attr-defined]
    if scanned < _MIN_FILES_SCANNED:
        failures.append(f"only {scanned} documents scanned")
    if carrying < _MIN_FILES_WITH_REFERENCES:
        failures.append(f"only {carrying} documents carry a reference")
    total = sum(counts.values())
    if total < _MIN_TOTAL_REFERENCES:
        failures.append(f"only {total} references extracted")
    for label, floor in _MIN_PER_CLASS.items():
        if counts[label] < floor:
            failures.append(f"only {counts[label]} {label} references (floor {floor})")
    return failures


_SYNTHETIC_DOC = """
# Synthetic

A real module: `gridalyn/twin/core/graph.py`.
Layer-relative shorthand: `core/graph.py`.
A study file: `scripts/config.py`.
"""

_BROKEN_SOURCE = "A moved module: `gridalyn/twin/core/no_such_module.py`.\n"
_RUNTIME_ARTIFACT = (
    "A run artifact: `instances/default/digital_twin/nope.json`, plus\n"
    "`outputs/json/nope.json` and `instances/default/digital_twin/x.parquet`.\n"
)


def _build_synthetic_repo(root: Path) -> Path:
    """Create a minimal repo with a layer package, a study and a document."""
    for layer in ("foundation", "twin", "projects"):
        package = root / "gridalyn" / layer
        package.mkdir(parents=True, exist_ok=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
    (root / "gridalyn" / "__init__.py").write_text("", encoding="utf-8")
    (root / "gridalyn" / "twin" / "core").mkdir(parents=True, exist_ok=True)
    (root / "gridalyn" / "twin" / "core" / "graph.py").write_text("", encoding="utf-8")
    study = root / "projects" / "demo" / "scripts"
    study.mkdir(parents=True, exist_ok=True)
    (study / "config.py").write_text("", encoding="utf-8")
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    document = docs / "note.md"
    document.write_text(_SYNTHETIC_DOC, encoding="utf-8")
    return document


class DocPathReferenceTests(unittest.TestCase):
    """Enforce and prove the documentation path-reference contract."""

    def setUp(self) -> None:
        """Scan the repository once per test."""
        self.report = checker.scan(_REPO_ROOT)

    # -- the gate ---------------------------------------------------------
    def test_no_unwaived_broken_references(self) -> None:
        """No stale SOURCE or UNCLASSIFIED reference outside the allowlist."""
        broken = tuple(self.report.stale) + tuple(self.report.unclassified)
        offenders = [f.located() for f in broken if not _is_waived(_key(f))]
        self.assertEqual(
            [],
            offenders,
            "documentation references a path that does not exist and that no "
            "class explains:\n" + "\n".join(offenders),
        )

    def test_allowlist_entries_still_match(self) -> None:
        """A fixed reference must be removed from the allowlist, not left behind.

        Entries whose document is absent from this checkout are skipped:
        CLAUDE.md and AGENTS.md are git-ignored, so CI legitimately has neither.
        """
        broken = {_key(f) for f in self.report.stale + self.report.unclassified}
        stale_entries = [
            f"{document} :: {reference}"
            for (document, reference) in sorted(_ALLOWLIST)
            if (_REPO_ROOT / document).is_file() and (document, reference) not in broken
        ]
        self.assertEqual(
            [],
            stale_entries,
            "these allowlist entries no longer match a broken reference; the "
            "reference has been fixed, so delete the entry rather than leave a "
            "standing permission:\n" + "\n".join(stale_entries),
        )

    # -- non-vacuity ------------------------------------------------------
    def test_classifier_is_not_vacuous(self) -> None:
        """Each class is found in non-trivial numbers, so silence means silence."""
        failures = _floor_failures(self.report)
        self.assertEqual(
            [],
            failures,
            "the classifier found too little to be trusted; a scanner that "
            "extracts nothing reports no stale references and proves nothing:\n"
            + "\n".join(failures),
        )

    def test_emptied_reference_list_trips_the_floor(self) -> None:
        """Mutation: an empty corpus must fail the floors, not pass them."""
        with self.subTest(corpus="empty"):
            with tempfile.TemporaryDirectory() as raw:
                empty = checker.scan(Path(raw))
                self.assertEqual(0, sum(empty.counts().values()), empty.counts())
                self.assertNotEqual(
                    [],
                    _floor_failures(empty),
                    "an empty corpus cleared every non-vacuity floor, so the "
                    "floors would not catch a broken scanner",
                )

    # -- the load-bearing mutations ---------------------------------------
    def test_synthetic_tree_mutations(self) -> None:
        """A broken source reference goes red; a runtime-artifact path stays green.

        Run against a synthetic repository rather than the live docs so the
        result depends on the classifier alone.
        """
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            document = _build_synthetic_repo(root)
            baseline = checker.scan(root)

            self.assertEqual(
                [], list(baseline.stale), [f.located() for f in baseline.findings]
            )
            self.assertEqual(0, len(baseline.unclassified))
            self.assertEqual(0, checker.main(["--root", str(root)]))

            document.write_text(
                _SYNTHETIC_DOC + _RUNTIME_ARTIFACT,
                encoding="utf-8",
            )
            with_runtime = checker.scan(root)
            self.assertEqual(
                [],
                [f.located() for f in with_runtime.stale]
                + [f.located() for f in with_runtime.unclassified],
                "a runtime-artifact path must not fail the gate; a classifier "
                "that flags it is an existence check, not a classifier",
            )
            self.assertGreater(
                with_runtime.counts()[checker.RUNTIME],
                baseline.counts()[checker.RUNTIME],
                "the runtime paths were not even seen, so the green result "
                "above proves nothing",
            )
            self.assertEqual(0, checker.main(["--root", str(root)]))

            document.write_text(
                _SYNTHETIC_DOC + _RUNTIME_ARTIFACT + _BROKEN_SOURCE,
                encoding="utf-8",
            )
            with_broken = checker.scan(root)
            self.assertEqual(
                ["gridalyn/twin/core/no_such_module.py"],
                [f.reference.path for f in with_broken.stale],
                [f.located() for f in with_broken.findings],
            )
            self.assertEqual(1, checker.main(["--root", str(root)]))

    # -- structural pins --------------------------------------------------
    def test_shorthand_prefixes_are_derived(self) -> None:
        """The prefix list is computed from the tree, not hardcoded.

        Recomputed here independently: every package directory under
        ``gridalyn/`` must appear, so adding an eighth layer extends the
        classifier without anyone editing a literal.
        """
        prefixes = set(checker._shorthand_prefixes(_REPO_ROOT))
        layers = {
            child.name
            for child in (_REPO_ROOT / "gridalyn").iterdir()
            if child.is_dir() and (child / "__init__.py").is_file()
        }
        self.assertGreaterEqual(len(layers), 7, sorted(layers))
        missing = {f"gridalyn/{layer}" for layer in layers} - prefixes
        self.assertEqual(set(), missing, sorted(prefixes))
        self.assertIn("gridalyn", prefixes)
        self.assertIn("docs", prefixes)
        self.assertNotIn("projects/__pycache__", prefixes)

    def test_runtime_rule_does_not_touch_the_filesystem(self) -> None:
        """RUNTIME is decided structurally, so the answer survives a clean checkout.

        This working tree contains ``instances/``, ``cache/`` and
        ``projects/*/outputs/``; CI's checkout does not. Deciding by existence
        would give the two environments different answers, which is precisely
        how a gate ships false-green.
        """
        runtime_paths = (
            "instances/default/digital_twin/base/metadata.json",
            "projects/ev_hosting_flex/outputs/json/congestion_risk.json",
            "datasets/hq/consumption.h5",
            "scenarios/S0_device_registry.parquet",
            "examples/generated/cache/",
        )
        for path in runtime_paths:
            with self.subTest(path=path):
                self.assertIsNotNone(checker._runtime_reason(path), path)
                # The same shape with a name nothing could have produced must
                # get the same answer, which is what "structural" means.
                fabricated = _fabricate(path)
                self.assertFalse((_REPO_ROOT / fabricated).exists(), fabricated)
                self.assertIsNotNone(checker._runtime_reason(fabricated), fabricated)

        # At least one listed path must exist here and at least one must not:
        # if all of them were absent the subtests above would pass even from an
        # existence check, and the property would be untested.
        present = [p for p in runtime_paths if (_REPO_ROOT / p).exists()]
        absent = [p for p in runtime_paths if not (_REPO_ROOT / p).exists()]
        self.assertNotEqual([], present, runtime_paths)
        self.assertNotEqual([], absent, runtime_paths)

        source_paths = (
            "gridalyn/foundation/platform/reports.py",
            "core/graph.py",
            "semantic/",
        )
        for path in source_paths:
            with self.subTest(path=path):
                self.assertIsNone(
                    checker._runtime_reason(path),
                    f"{path} is a package path, not a run artifact",
                )

    # -- measurement ------------------------------------------------------
    def test_unclassified_blind_spot_is_measured(self) -> None:
        """The taxonomy's blind spot is reported as a number, not implied zero."""
        counts = self.report.counts()
        unclassified = counts[checker.UNCLASSIFIED]
        listed = "\n".join(f"  {f.located()}" for f in self.report.unclassified)
        print(
            f"\ndoc path references: {sum(counts.values())} across "
            f"{self.report.files_with_references} of {self.report.files_scanned} "
            f"documents -- "
            + ", ".join(f"{label} {counts[label]}" for label in checker.CLASSES)
            + f"; {len(self.report.stale)} stale SOURCE"
            f"\ndoc path blind spot: {unclassified} UNCLASSIFIED reference(s)"
            + (f"\n{listed}" if listed else "")
            + f"\ndoc path fenced-block blind spot: {self.report.skipped_in_fences} "
            "path-shaped words inside fenced code blocks are not scanned"
        )
        self.assertLessEqual(
            unclassified,
            _MAX_UNCLASSIFIED,
            "too many references match none of the three classes; that means "
            "the taxonomy is wrong, not that the docs got worse:\n" + listed,
        )


if __name__ == "__main__":
    unittest.main()
