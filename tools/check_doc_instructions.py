"""Six-class classifier for the fenced instruction blocks in the documentation.

Why a ledger and not a "run everything" script
----------------------------------------------
The documentation surface carries 350 fenced code blocks. Executing all of them
is neither possible nor meaningful: most are not commands at all, several are
destructive, one chain takes six hours, and a large fraction only works as an
*ordered* group because block 5 of a tutorial consumes the project block 3
created. A gate that tried to run them would be red forever; a gate that ran
none of them would prove nothing.

So the blocks are **classified**, once, by a human reading each one, and the
classification is pinned in a tracked ledger. This module is the machinery that
extracts the blocks, offers a structural first-pass suggestion, and checks the
ledger against the corpus. It never decides a class on its own authority: the
suggestion is advice, the ledger is the record, and a re-run never overwrites a
reviewed entry.

The six classes
---------------
``RUNNABLE-INDEPENDENT``
    A self-contained command that can be run alone in a prepared environment.
    Verifying it means running it.

``RUNNABLE-SEQUENCE``
    A member of a file-scoped ORDERED chain that shares one scratch workspace --
    the tutorial that runs ``gridalyn project init my_case`` in block 3 and
    ``uv run python scripts/build.py`` from inside it in block 5. Each member
    block still gets its own ledger entry (so coverage stays 1:1 and every block
    is hash-pinned), and it names a **sequence entry** that owns the ordered
    member list and the single shared verdict. Running member 5 alone is
    meaningless, so the verdict is a property of the chain, not of the block.

``ILLUSTRATIVE``
    Not executable as written: output samples, YAML/JSON fragments, directory
    trees, mermaid diagrams, pseudo-commands with ``<placeholder>`` arguments,
    API sketches. Verifying it means reading it, not running it.

``LONG-RUNNING``
    Over ten minutes. The ``ev_hosting_flex`` flagship run (~6 h) is the
    canonical case. Documented rather than executed, with the decision recorded.

``DESTRUCTIVE``
    Deletes state or mutates a remote: ``rm``, ``git push``, ``mkdocs gh-deploy``,
    ``git clean``, ``docker compose down -v``. Never executed by a verification
    pass.

``ENV-DEPENDENT``
    Needs a runtime beyond the Python environment -- npm, docker, a network
    fetch beyond pip. Documented, not executed, because a red result would
    measure the runner rather than the documentation.

Block identity, and why the hash is the whole point
---------------------------------------------------
A block is keyed by ``<repo-relative path>#<0-based ordinal within the file>``
and its entry pins ``sha1`` of the block's content. The key is stable so a
wave-2 verdict fragment can be merged as a plain field update; the hash is what
makes the pin *mean* something. Edit a classified block and the hash stops
matching: the entry is reported as stale and must be re-reviewed, because the
verdict was evidence about text that no longer exists. This is the doc-path
gate's hash-pinning lesson applied to instructions.

Ordinals shift when a block is inserted mid-file, which is deliberate: an
insertion invalidates the hashes of everything after it and forces exactly the
re-review that a silently-renumbered ledger would skip.

The ledger schema
-----------------
``docs/development/instruction-ledger.json``, tracked, valid JSON, two record
sections plus a header::

    {
      "schema_version": "1.0",
      "corpus": "docs/**/*.md + README.md, minus git-ignored documents",
      "blocks": {
        "docs/getting-started/quickstart.md#3": {
          "class":     one of CLASSES,
          "auto":      the structural suggestion at review time (advice only),
          "family":    "getting-started" | "platform" | "development" |
                       "UNASSIGNED",
          "file":      repo-relative path,
          "ordinal":   0-based index of the block within its file,
          "line":      1-indexed line of the opening fence,
          "language":  the fence's language tag ("" when bare),
          "sha1":      sha1 of the block's content,
          "sequence":  sequence id when class is RUNNABLE-SEQUENCE, else null,
          "verdict":   one of VERDICTS, or null when the sequence owns it,
          "rationale": why this class -- required non-empty for the four
                       non-runnable classes,
          "evidence":  reference to the evidence that produced the verdict,
                       or null while pending,
          "date":      ISO date the verdict was evidenced, or null = PENDING
        },
        ...
      },
      "sequences": {
        "docs/tutorials/build-minimal-digital-twin.md#seq0": {
          "file":      repo-relative path,
          "members":   [ordinals, in execution order],
          "workspace": one-line description of the shared scratch state,
          "verdict":   one of VERDICTS,
          "rationale": "",
          "evidence":  null,
          "date":      null
        },
        ...
      }
    }

``date: null`` is the pending marker: the ``verdict`` field carries the *initial*
state, not an evidenced one. A wave-2 executor evidences an entry by writing
``verdict``, ``evidence`` and ``date`` -- three field updates, no restructuring,
which is what makes a fragment merge mechanical.

What this tool checks
---------------------
* every extracted block has a ledger entry (**unclassified** otherwise);
* every entry's ``sha1`` still matches the block it names (**stale** otherwise);
* no entry names a block the corpus no longer has (**orphaned**);
* the recorded ``file``/``ordinal``/``family`` agree with the corpus;
* every ``RUNNABLE-SEQUENCE`` block names a sequence that lists its ordinal, and
  every sequence lists only blocks of that class from its own file;
* ``class``, ``verdict`` and ``family`` take values from the declared sets, and
  the non-runnable classes carry a non-empty rationale.

Exit status is 0 when the ledger covers the corpus exactly, else 1 with one
located finding per problem.

The corpus, and why it is smaller than ``docs/``
------------------------------------------------
``docs/**/*.md`` plus ``README.md``, walked from disk, **minus the documents git
ignores**. Ledger coverage has to be exact in both directions -- every block
classified *and* no entry naming a block that is not there -- so a document that
exists on a developer's machine and not in CI cannot be in the corpus: its
entries would be "unclassified" here and "orphaned" there, and the gate would
answer differently in the two places. That is the same failure mode the doc-path
gate guards against by keying its floors to a clean checkout.

Measured on this tree: 84 markdown documents are walked, **7 of which
``.gitignore`` lines 146-149 exclude** -- ``docs/development/ai-agent-guide.md``,
``docs/development/cleanup-inventory.md``,
``docs/development/release-cleanup-audit.md`` and the four
``docs/development/agent-task-templates/`` files, all AI-assistant records
deliberately kept out of the public repository, together carrying 11 blocks.
``CLAUDE.md`` and ``AGENTS.md`` are excluded for the same reason, one level up in
:data:`_ROOT_DOCS`. The corpus is therefore **77 documents and 350 blocks**, and
that is what a clean checkout carries.

The exclusion is a declared list rather than a ``git`` call, so classification
stays a pure function of the tree; ``tests/test_doc_instructions.py`` checks the
list against ``git check-ignore`` in both directions, so an un-ignored document
fails until its blocks are classified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER_REL = "docs/development/instruction-ledger.json"

# --------------------------------------------------------------------------
# Classes
# --------------------------------------------------------------------------
RUNNABLE_INDEPENDENT = "RUNNABLE-INDEPENDENT"
RUNNABLE_SEQUENCE = "RUNNABLE-SEQUENCE"
ILLUSTRATIVE = "ILLUSTRATIVE"
LONG_RUNNING = "LONG-RUNNING"
DESTRUCTIVE = "DESTRUCTIVE"
ENV_DEPENDENT = "ENV-DEPENDENT"

CLASSES: tuple[str, ...] = (
    RUNNABLE_INDEPENDENT,
    RUNNABLE_SEQUENCE,
    ILLUSTRATIVE,
    LONG_RUNNING,
    DESTRUCTIVE,
    ENV_DEPENDENT,
)

#: The classes whose verification means *executing* the block.
RUNNABLE_CLASSES: frozenset[str] = frozenset({RUNNABLE_INDEPENDENT, RUNNABLE_SEQUENCE})
#: The classes documented rather than executed; each needs a rationale.
DOCUMENTED_CLASSES: frozenset[str] = frozenset(set(CLASSES) - RUNNABLE_CLASSES)

# --------------------------------------------------------------------------
# Verdicts
# --------------------------------------------------------------------------
UNVERIFIED = "UNVERIFIED"
PASS_AS_WRITTEN = "PASS-AS-WRITTEN"
FIXED_CODE = "FIXED-CODE"
FIXED_DOC = "FIXED-DOC"
DOCUMENTED = "DOCUMENTED"

VERDICTS: tuple[str, ...] = (
    UNVERIFIED,
    PASS_AS_WRITTEN,
    FIXED_CODE,
    FIXED_DOC,
    DOCUMENTED,
)

# --------------------------------------------------------------------------
# Families
# --------------------------------------------------------------------------
#: Sentinel for a document that no family claims. Recorded honestly rather than
#: folded into a neighbouring family: a documentation tree that grew a directory
#: nobody owns is a finding, and inventing an owner would hide it.
UNASSIGNED = "UNASSIGNED"

#: Directory prefixes (and one exact filename) per verification family. Ordered
#: so the first match wins; the sets are disjoint by construction, and
#: :func:`unassigned_files` reports whatever falls through.
FAMILY_PREFIXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "getting-started",
        ("docs/getting-started/", "docs/reference/", "README.md"),
    ),
    (
        "platform",
        (
            "docs/platform/",
            "docs/tutorials/",
            "docs/flexibility/",
            "docs/workflows/",
            "docs/projects/",
            "docs/sdk/",
            "docs/concepts/",
            # Assigned to this family by orchestrator ruling during Phase 7:
            # the original three-family split left these unowned, and their
            # runnable blocks were executed under the platform family. Keeping
            # them out would leave real instructions verified by nobody.
            # ``applications/`` carries no fenced block today, but ownership is
            # about who runs a document's instructions WHEN it gains them --
            # claiming it now is what lets the gate assert that the split
            # covers the whole corpus rather than all-but-a-pinned-remainder.
            "docs/index.md",
            "docs/semantic-layer/",
            "docs/applications/",
        ),
    ),
    ("development", ("docs/development/",)),
)

FAMILIES: tuple[str, ...] = tuple(name for name, _ in FAMILY_PREFIXES) + (UNASSIGNED,)

# --------------------------------------------------------------------------
# Corpus
# --------------------------------------------------------------------------
_ROOT_DOCS: tuple[str, ...] = ("README.md",)
_DOCS_DIR = "docs"

#: Documents under ``docs/`` that ``.gitignore`` excludes, and that a clean
#: checkout therefore does not carry. Kept out of the corpus because ledger
#: coverage must be exact: an entry for one of these would read "unclassified"
#: on a machine that has the file and "orphaned" on one that does not.
#:
#: Every path here is checked against ``git check-ignore`` by
#: ``tests/test_doc_instructions.py``, in both directions -- so un-ignoring one
#: fails the gate until its blocks are classified, and ignoring a new document
#: fails until it is listed here.
EXCLUDED_DOCS: tuple[str, ...] = (
    "docs/development/agent-task-templates/add-project.md",
    "docs/development/agent-task-templates/add-sdk-feature.md",
    "docs/development/agent-task-templates/add-sense-check.md",
    "docs/development/agent-task-templates/update-docs.md",
    "docs/development/ai-agent-guide.md",
    "docs/development/cleanup-inventory.md",
    "docs/development/release-cleanup-audit.md",
)

# --------------------------------------------------------------------------
# Structural auto-suggestion
# --------------------------------------------------------------------------
#: Fence languages whose content could conceivably be executed. Everything else
#: (text, yaml, json, mermaid, cypher, a bare fence) is ILLUSTRATIVE on sight.
_COMMAND_LANGUAGES: frozenset[str] = frozenset(
    {"bash", "sh", "shell", "console", "zsh", "python", "py"}
)
_SHELL_LANGUAGES: frozenset[str] = frozenset({"bash", "sh", "shell", "console", "zsh"})

#: Word-boundary patterns for commands that delete state or mutate a remote.
_DESTRUCTIVE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\brm\s+-", "`rm -` deletes files"),
    (r"\brmdir\b", "`rmdir` deletes a directory"),
    (r"\bgit\s+push\b", "`git push` mutates a remote"),
    (r"\bgit\s+clean\b", "`git clean` deletes untracked state"),
    (r"\bgit\s+reset\s+--hard\b", "`git reset --hard` discards work"),
    (r"\bgit\s+stash\b", "`git stash` hides working-tree state"),
    (r"\bgh-deploy\b", "`mkdocs gh-deploy` publishes to a remote branch"),
    (r"\bdocker\s+compose\s+down\b", "`docker compose down` tears down state"),
    (r"\bshutil\.rmtree\b", "`shutil.rmtree` deletes a tree"),
)

#: Commands that need a runtime beyond the Python environment.
_ENV_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bnpm\b", "needs Node/npm"),
    (r"\bnpx\b", "needs Node/npx"),
    (r"\bdocker\b", "needs Docker"),
    (r"\byarn\b", "needs Node/yarn"),
    (r"\bpnpm\b", "needs Node/pnpm"),
    (r"\bcurl\s+http", "fetches over the network"),
    (r"\bwget\b", "fetches over the network"),
    (r"\bapt-get\b", "needs a system package manager"),
    (r"\bbrew\s+install\b", "needs a system package manager"),
)

#: Commands measured or documented to exceed ten minutes.
_LONG_RUNNING_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"ev_hosting_flex", "the flagship study run is ~6 h"),
    (r"admm_thermal_consensus", "the sibling ADMM study is a long run"),
    (r"\bpytest\b(?![^\n]*(-k|tests/test_))", "a full pytest sweep is minutes-scale"),
)


@dataclass(frozen=True)
class Block:
    """One fenced code block extracted from the documentation.

    Attributes:
        file: Repo-relative path of the document it was found in.
        ordinal: 0-based index of this block within that document.
        line: 1-indexed line number of the opening fence.
        language: The fence's language tag, or ``""`` for a bare fence.
        content: The block's body, excluding both fence lines.
    """

    file: str
    ordinal: int
    line: int
    language: str
    content: str

    @property
    def key(self) -> str:
        """Return the stable ledger key ``<file>#<ordinal>``."""
        return f"{self.file}#{self.ordinal}"

    @property
    def sha1(self) -> str:
        """Return the sha1 of the block's content, the pin that detects edits."""
        return hashlib.sha1(self.content.encode("utf-8")).hexdigest()

    @property
    def family(self) -> str:
        """Return the verification family of the document holding this block."""
        return family_of(self.file)

    def located(self, message: str) -> str:
        """Return a ``path:line: key: message`` line naming this block."""
        return f"{self.file}:{self.line}: {self.key}: {message}"


@dataclass(frozen=True)
class Finding:
    """One problem with the ledger's coverage of the corpus."""

    kind: str
    key: str
    where: str
    detail: str

    def located(self) -> str:
        """Return a located, remediating one-line rendering of the finding."""
        return f"{self.where}: {self.kind}: {self.key}: {self.detail}"


@dataclass(frozen=True)
class Audit:
    """Result of checking a ledger against the extracted corpus."""

    blocks: tuple[Block, ...]
    files_scanned: int
    unclassified: tuple[Finding, ...]
    stale: tuple[Finding, ...]
    orphaned: tuple[Finding, ...]
    invalid: tuple[Finding, ...]
    ledger: dict[str, object] = field(default_factory=dict)

    @property
    def findings(self) -> tuple[Finding, ...]:
        """Return every finding, in the order the report prints them."""
        return self.unclassified + self.stale + self.orphaned + self.invalid

    def class_counts(self) -> dict[str, int]:
        """Return the per-class block counts, zero-filled."""
        entries = _entries(self.ledger)
        tally = Counter(str(entry.get("class")) for entry in entries.values())
        return {label: tally.get(label, 0) for label in CLASSES}

    def family_counts(self) -> dict[str, int]:
        """Return the per-family block counts, zero-filled."""
        tally = Counter(block.family for block in self.blocks)
        return {name: tally.get(name, 0) for name in FAMILIES}

    def runnable_by_family(self) -> dict[str, int]:
        """Return how many blocks of a runnable class each family carries.

        This is the number wave-2 execution is sized against: a family's
        RUNNABLE-INDEPENDENT blocks plus its RUNNABLE-SEQUENCE members.
        """
        entries = _entries(self.ledger)
        tally: Counter[str] = Counter()
        for block in self.blocks:
            entry = entries.get(block.key)
            if entry is not None and entry.get("class") in RUNNABLE_CLASSES:
                tally[block.family] += 1
        return {name: tally.get(name, 0) for name in FAMILIES}

    def sequences(self) -> dict[str, dict[str, object]]:
        """Return the ledger's sequence records."""
        raw = self.ledger.get("sequences", {})
        return dict(raw) if isinstance(raw, dict) else {}


# --------------------------------------------------------------------------
# Corpus walk and extraction
# --------------------------------------------------------------------------
def document_files(root: Path = ROOT) -> list[Path]:
    """Return the documentation corpus, walked from disk rather than from git.

    Everything git ignores is dropped -- ``CLAUDE.md`` and ``AGENTS.md`` by their
    absence from :data:`_ROOT_DOCS`, the seven AI-assistant records under
    ``docs/development/`` by :data:`EXCLUDED_DOCS`. Including a git-ignored
    document would make the gate answer differently on a developer's tree and in
    CI, which is the one thing an exact-coverage gate cannot survive.
    """
    files = [root / name for name in _ROOT_DOCS]
    docs = root / _DOCS_DIR
    if docs.is_dir():
        files += sorted(docs.rglob("*.md"))
    base = root.resolve()
    excluded = set(EXCLUDED_DOCS)
    return [
        path
        for path in files
        if path.is_file()
        and path.resolve().relative_to(base).as_posix() not in excluded
    ]


_FENCE_OPEN = re.compile(r"^(```+|~~~+)[ \t]*([^\s`]*)")
_FENCE_CLOSE = re.compile(r"^(```+|~~~+)[ \t]*$")


def extract_file_blocks(text: str, relative: str) -> list[Block]:
    """Return every fenced block in one document, in document order.

    A fence opens on a line whose first non-blank characters are three or more
    backticks or tildes, and closes on the next line that is a bare run of the
    same marker. Nested fences are not a thing markdown supports at this depth,
    so the state machine is deliberately two-state: anything between an opening
    fence and its closer is content, including a line that looks like a fence
    but carries an info string.

    Args:
        text: The document's full text.
        relative: Repo-relative path, recorded on each block.

    Returns:
        The document's blocks, ordinal 0 upward.
    """
    blocks: list[Block] = []
    body: list[str] = []
    open_line = 0
    language = ""
    in_fence = False
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if not in_fence:
            opened = _FENCE_OPEN.match(stripped)
            if opened is not None:
                in_fence = True
                language = opened.group(2).lower()
                open_line = number
                body = []
            continue
        if _FENCE_CLOSE.match(stripped) is not None:
            blocks.append(
                Block(
                    file=relative,
                    ordinal=len(blocks),
                    line=open_line,
                    language=language,
                    content="\n".join(body) + "\n" if body else "",
                )
            )
            in_fence = False
            continue
        body.append(line)
    return blocks


def extract_blocks(root: Path = ROOT) -> tuple[Block, ...]:
    """Return every fenced block across the whole documentation corpus."""
    blocks: list[Block] = []
    for path in document_files(root):
        relative = path.resolve().relative_to(root.resolve()).as_posix()
        blocks += extract_file_blocks(path.read_text(encoding="utf-8"), relative)
    return tuple(blocks)


# --------------------------------------------------------------------------
# Families
# --------------------------------------------------------------------------
def family_of(relative: str) -> str:
    """Return the verification family owning a document, or ``UNASSIGNED``.

    Args:
        relative: Repo-relative path of a corpus document.

    Returns:
        The first family whose prefix set claims the path, else ``UNASSIGNED``.
    """
    for name, prefixes in FAMILY_PREFIXES:
        for prefix in prefixes:
            if relative == prefix or relative.startswith(prefix):
                return name
    return UNASSIGNED


def unassigned_files(root: Path = ROOT) -> tuple[str, ...]:
    """Return the corpus documents no family claims, sorted.

    A non-empty result is a real finding about the documentation tree, not a
    bug in this tool: the family split is what wave-2 execution is partitioned
    by, so a document outside all of them would go unverified in silence.
    """
    return tuple(
        sorted(
            path.resolve().relative_to(root.resolve()).as_posix()
            for path in document_files(root)
            if family_of(path.resolve().relative_to(root.resolve()).as_posix())
            == UNASSIGNED
        )
    )


# --------------------------------------------------------------------------
# Structural auto-suggestion
# --------------------------------------------------------------------------
def _first_match(
    content: str, patterns: tuple[tuple[str, str], ...]
) -> tuple[str, str] | None:
    """Return the first ``(pattern, reason)`` that matches, or ``None``."""
    for pattern, reason in patterns:
        if re.search(pattern, content):
            return pattern, reason
    return None


def suggest_class(block: Block) -> tuple[str, str]:
    """Return a structural first-pass class for a block, with its reason.

    This is **advice**, not a decision. It is deliberately shallow -- it looks at
    the fence language and at command names, and it cannot tell a real command
    from a prose sentence that happens to contain one. Every ledger entry is
    reviewed by reading the block; where the review disagrees, the ledger's
    ``class`` differs from its ``auto`` and that disagreement is visible.

    Order matters: the language test runs first, so a ``text`` block quoting the
    word ``docker`` in sample output is not mistaken for a container command.

    Args:
        block: The extracted block to suggest a class for.

    Returns:
        A ``(class, reason)`` pair; the class is always a member of
        :data:`CLASSES`.
    """
    if block.language not in _COMMAND_LANGUAGES:
        tag = block.language or "(bare fence)"
        return ILLUSTRATIVE, f"fence language {tag} is not executable as written"
    content = block.content
    hit = _first_match(content, _DESTRUCTIVE_PATTERNS)
    if hit is not None:
        return DESTRUCTIVE, hit[1]
    hit = _first_match(content, _ENV_PATTERNS)
    if hit is not None:
        return ENV_DEPENDENT, hit[1]
    if block.language in _SHELL_LANGUAGES:
        hit = _first_match(content, _LONG_RUNNING_PATTERNS)
        if hit is not None:
            return LONG_RUNNING, hit[1]
    return RUNNABLE_INDEPENDENT, f"{block.language} block with no blocking marker"


# --------------------------------------------------------------------------
# Ledger IO
# --------------------------------------------------------------------------
def _entries(ledger: dict[str, object]) -> dict[str, dict[str, object]]:
    """Return the ledger's block records, tolerating a malformed document."""
    raw = ledger.get("blocks", {})
    if not isinstance(raw, dict):
        return {}
    return {key: value for key, value in raw.items() if isinstance(value, dict)}


def load_ledger(path: Path) -> dict[str, object]:
    """Return the parsed ledger, or an empty skeleton when it does not exist.

    Args:
        path: Absolute path of the ledger JSON.

    Returns:
        The parsed document.

    Raises:
        ValueError: If the file exists but is not a JSON object, naming the path
            and what the document must be.
    """
    if not path.is_file():
        return {"schema_version": "1.0", "blocks": {}, "sequences": {}}
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError(
            f"{path}: the instruction ledger must be a JSON object with "
            f"'blocks' and 'sequences' keys, found {type(parsed).__name__}"
        )
    return parsed


def write_ledger(path: Path, ledger: dict[str, object]) -> None:
    """Write the ledger as stable, diff-friendly JSON with a trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(ledger, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )


def suggest_entry(block: Block) -> dict[str, object]:
    """Return a draft ledger entry for a block, pre-filled from the suggester.

    The draft is a starting point for review: ``class`` equals ``auto``, and a
    reviewer who disagrees edits ``class`` and leaves ``auto`` alone so the
    override stays visible.
    """
    auto, reason = suggest_class(block)
    runnable = auto in RUNNABLE_CLASSES
    return {
        "class": auto,
        "auto": auto,
        "family": block.family,
        "file": block.file,
        "ordinal": block.ordinal,
        "line": block.line,
        "language": block.language,
        "sha1": block.sha1,
        "sequence": None,
        "verdict": UNVERIFIED if runnable else DOCUMENTED,
        "rationale": "" if runnable else reason,
        "evidence": None,
        "date": None,
    }


def merge_suggestions(
    ledger: dict[str, object], blocks: tuple[Block, ...]
) -> tuple[dict[str, object], int]:
    """Return the ledger with drafts added for uncovered blocks, and how many.

    Existing entries are **never** touched, however wrong they look: a reviewed
    class is a human judgement and this tool has no standing to overwrite one.
    Only blocks with no entry at all gain a draft.
    """
    merged = dict(ledger)
    entries = dict(_entries(merged))
    added = 0
    for block in blocks:
        if block.key in entries:
            continue
        entries[block.key] = suggest_entry(block)
        added += 1
    merged["blocks"] = {
        block.key: entries[block.key] for block in blocks if block.key in entries
    }
    merged.setdefault("sequences", {})
    return merged, added


# --------------------------------------------------------------------------
# Audit
# --------------------------------------------------------------------------
def _entry_problems(block: Block, entry: dict[str, object]) -> list[str]:
    """Return every contract violation in one ledger entry, as messages."""
    problems: list[str] = []
    label = entry.get("class")
    if label not in CLASSES:
        problems.append(
            f"class {label!r} is not one of {', '.join(CLASSES)}",
        )
    if entry.get("family") != block.family:
        problems.append(
            f"family {entry.get('family')!r} disagrees with the corpus "
            f"({block.family!r}); the document moved, so re-file the entry"
        )
    if entry.get("file") != block.file or entry.get("ordinal") != block.ordinal:
        problems.append(
            f"file/ordinal {entry.get('file')!r}#{entry.get('ordinal')!r} "
            f"disagrees with the key; regenerate with --suggest"
        )
    verdict = entry.get("verdict")
    if label == RUNNABLE_SEQUENCE:
        if verdict is not None:
            problems.append(
                "a RUNNABLE-SEQUENCE block must leave verdict null; the "
                "sequence entry owns the verdict for the whole chain"
            )
        if not entry.get("sequence"):
            problems.append(
                "a RUNNABLE-SEQUENCE block must name its sequence in "
                "'sequence' (the chain that owns its verdict)"
            )
    else:
        if verdict not in VERDICTS:
            problems.append(f"verdict {verdict!r} is not one of {', '.join(VERDICTS)}")
        if entry.get("sequence") is not None:
            problems.append(
                f"only a RUNNABLE-SEQUENCE block may name a sequence; "
                f"class is {label!r}"
            )
    if label in DOCUMENTED_CLASSES and not str(entry.get("rationale") or "").strip():
        problems.append(
            f"class {label} is documented rather than executed, so "
            f"'rationale' must say why (it is empty)"
        )
    return problems


def _member_problems(
    name: str,
    where: str,
    key: str,
    entry: dict[str, object] | None,
    known: bool,
) -> Finding | None:
    """Return the violation in one declared sequence member, or ``None``."""
    if not known or entry is None:
        return Finding(
            "invalid-sequence", name, where, f"member {key} has no block entry"
        )
    if entry.get("class") != RUNNABLE_SEQUENCE:
        return Finding(
            "invalid-sequence",
            name,
            where,
            f"member {key} is classified {entry.get('class')!r}, "
            f"not {RUNNABLE_SEQUENCE}",
        )
    if entry.get("sequence") != name:
        return Finding(
            "invalid-sequence",
            name,
            where,
            f"member {key} names sequence {entry.get('sequence')!r}",
        )
    return None


def _record_problems(
    name: str,
    record: object,
    blocks_by_key: dict[str, Block],
    entries: dict[str, dict[str, object]],
    claimed: dict[str, str],
) -> list[Finding]:
    """Return every violation in one sequence record, recording its members."""
    if not isinstance(record, dict):
        return [Finding("invalid-sequence", name, name, "record is not an object")]
    where = str(record.get("file", name))
    members = record.get("members")
    if not isinstance(members, list) or not members:
        return [
            Finding(
                "invalid-sequence",
                name,
                where,
                "'members' must be a non-empty list of ordinals in execution order",
            )
        ]
    findings: list[Finding] = []
    if record.get("verdict") not in VERDICTS:
        findings.append(
            Finding(
                "invalid-sequence",
                name,
                where,
                f"verdict {record.get('verdict')!r} is not one of "
                f"{', '.join(VERDICTS)}",
            )
        )
    for ordinal in members:
        key = f"{record.get('file')}#{ordinal}"
        claimed.setdefault(key, name)
        problem = _member_problems(
            name, where, key, entries.get(key), key in blocks_by_key
        )
        if problem is not None:
            findings.append(problem)
    return findings


def _unclaimed_member_problem(
    key: str,
    entry: dict[str, object],
    sequences: dict[str, object],
    claimed: dict[str, str],
) -> Finding | None:
    """Return the violation in a block that names a sequence, or ``None``."""
    name = entry.get("sequence")
    where = str(entry.get("file", key))
    if not isinstance(name, str) or name not in sequences:
        return Finding(
            "invalid-sequence",
            key,
            where,
            f"names sequence {name!r}, which the 'sequences' section does not "
            f"declare",
        )
    if claimed.get(key) != name:
        return Finding(
            "invalid-sequence",
            key,
            where,
            f"sequence {name!r} does not list ordinal {entry.get('ordinal')} "
            f"among its members",
        )
    return None


def _sequence_problems(
    ledger: dict[str, object], blocks_by_key: dict[str, Block]
) -> list[Finding]:
    """Return every contract violation across the ledger's sequence records.

    Checked in both directions: a sequence may not list a member that is not a
    ``RUNNABLE-SEQUENCE`` block naming it back, and a ``RUNNABLE-SEQUENCE`` block
    may not name a sequence that does not list it. Either half alone would let a
    member drop out of a chain while still looking classified.
    """
    raw = ledger.get("sequences", {})
    sequences: dict[str, object] = raw if isinstance(raw, dict) else {}
    entries = _entries(ledger)
    claimed: dict[str, str] = {}

    findings: list[Finding] = []
    for name, record in sorted(sequences.items()):
        findings += _record_problems(name, record, blocks_by_key, entries, claimed)
    for key, entry in sorted(entries.items()):
        if entry.get("class") != RUNNABLE_SEQUENCE:
            continue
        problem = _unclaimed_member_problem(key, entry, sequences, claimed)
        if problem is not None:
            findings.append(problem)
    return findings


def audit(root: Path = ROOT, ledger_path: Path | None = None) -> Audit:
    """Check the tracked ledger against the extracted corpus.

    Args:
        root: Repository root to scan.
        ledger_path: Ledger location; defaults to :data:`LEDGER_REL` under
            ``root``.

    Returns:
        An :class:`Audit` carrying the blocks and every finding, grouped by kind.
    """
    path = ledger_path if ledger_path is not None else root / LEDGER_REL
    ledger = load_ledger(path)
    blocks = extract_blocks(root)
    by_key = {block.key: block for block in blocks}
    entries = _entries(ledger)

    unclassified: list[Finding] = []
    stale: list[Finding] = []
    invalid: list[Finding] = []
    for block in blocks:
        entry = entries.get(block.key)
        if entry is None:
            unclassified.append(
                Finding(
                    "unclassified",
                    block.key,
                    f"{block.file}:{block.line}",
                    f"new {block.language or 'bare'} block with no ledger entry; "
                    f"run `python tools/check_doc_instructions.py --suggest` and "
                    f"review the draft",
                )
            )
            continue
        if entry.get("sha1") != block.sha1:
            stale.append(
                Finding(
                    "hash-mismatch",
                    block.key,
                    f"{block.file}:{block.line}",
                    f"content changed since classification (ledger "
                    f"{str(entry.get('sha1'))[:12]}, corpus {block.sha1[:12]}); "
                    f"re-review the block and update 'sha1' plus any verdict it "
                    f"invalidates",
                )
            )
        for message in _entry_problems(block, entry):
            invalid.append(
                Finding(
                    "invalid-entry", block.key, f"{block.file}:{block.line}", message
                )
            )

    orphaned = [
        Finding(
            "orphaned",
            key,
            str(entry.get("file", LEDGER_REL)),
            "ledger entry names a block the corpus no longer has; the block was "
            "deleted or renumbered, so delete the entry rather than leave a "
            "standing classification",
        )
        for key, entry in sorted(entries.items())
        if key not in by_key
    ]
    invalid += _sequence_problems(ledger, by_key)

    return Audit(
        blocks=blocks,
        files_scanned=len(document_files(root)),
        unclassified=tuple(unclassified),
        stale=tuple(stale),
        orphaned=tuple(orphaned),
        invalid=tuple(invalid),
        ledger=ledger,
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _print_report(result: Audit, root: Path) -> None:
    """Print the corpus size, the class and family distributions, and the gaps."""
    classes = result.class_counts()
    families = result.family_counts()
    runnable = result.runnable_by_family()
    print(
        f"documentation corpus: {result.files_scanned} files, "
        f"{len(result.blocks)} fenced blocks"
    )
    print("classes:")
    for label in CLASSES:
        print(f"  {label:<21} {classes[label]:>4}")
    print(f"sequences: {len(result.sequences())}")
    print("families (blocks / runnable-family members):")
    for name in FAMILIES:
        print(f"  {name:<21} {families[name]:>4} / {runnable[name]:>4}")
    unassigned = unassigned_files(root)
    if unassigned:
        print(f"documents no family claims ({len(unassigned)}):")
        for name in unassigned:
            print(f"  {name}")
    overrides = [
        key
        for key, entry in sorted(_entries(result.ledger).items())
        if entry.get("auto") != entry.get("class")
    ]
    print(f"human review overrode the structural suggestion on {len(overrides)} blocks")


def _print_blocks(result: Audit, wanted: str, root: Path) -> None:
    """Print every block of a given class, one located line each."""
    entries = _entries(result.ledger)
    for block in result.blocks:
        entry = entries.get(block.key)
        label = entry.get("class") if entry else suggest_class(block)[0]
        if label == wanted:
            head = block.content.strip().splitlines()
            preview = head[0][:70] if head else "(empty)"
            print(f"{block.located(preview)}")


def _build_parser() -> argparse.ArgumentParser:
    """Return the argument parser for the instruction-ledger CLI."""
    parser = argparse.ArgumentParser(
        prog="check_doc_instructions.py",
        description=(
            "Check the tracked instruction ledger against every fenced code "
            "block in docs/**/*.md and README.md. Exits 1 when a block is "
            "unclassified, when a classified block's content has changed, when "
            "an entry names a block that no longer exists, or when an entry "
            "violates the schema."
        ),
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="print the corpus size and the class/family distributions",
    )
    parser.add_argument(
        "--list",
        choices=CLASSES,
        help="list every block of the given class, with its location",
    )
    parser.add_argument(
        "--suggest",
        action="store_true",
        help=(
            "add a draft entry for every block the ledger does not cover and "
            "write it back; existing entries are never modified"
        ),
    )
    parser.add_argument(
        "--dump",
        type=Path,
        help="write every block's full content to a JSON file, for review",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="repository root to scan (default: the repo this file lives in)",
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        help=f"ledger location (default: <root>/{LEDGER_REL})",
    )
    return parser


def _dump_blocks(blocks: tuple[Block, ...], destination: Path) -> None:
    """Write every block's full content to JSON so a reviewer can read them."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(
            [
                {
                    "key": block.key,
                    "file": block.file,
                    "ordinal": block.ordinal,
                    "line": block.line,
                    "language": block.language,
                    "family": block.family,
                    "sha1": block.sha1,
                    "auto": suggest_class(block)[0],
                    "content": block.content,
                }
                for block in blocks
            ],
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    """Audit the ledger and return 0 when it covers the corpus exactly."""
    args = _build_parser().parse_args(argv)
    root = args.root.resolve()
    ledger_path = args.ledger if args.ledger is not None else root / LEDGER_REL

    if args.dump is not None:
        _dump_blocks(extract_blocks(root), args.dump)

    if args.suggest:
        ledger, added = merge_suggestions(
            load_ledger(ledger_path), extract_blocks(root)
        )
        write_ledger(ledger_path, ledger)
        print(f"{ledger_path}: added {added} draft entr(ies); review every one")

    result = audit(root, ledger_path)
    if args.report:
        _print_report(result, root)
    if args.list:
        _print_blocks(result, args.list, root)

    findings = result.findings
    if findings:
        print(f"documentation instruction ledger FAILED ({len(findings)} finding(s)):")
        for finding in findings:
            print(f"  {finding.located()}")
        return 1
    print(
        f"documentation instruction ledger OK "
        f"({len(result.blocks)} blocks classified)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
