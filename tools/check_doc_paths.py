"""Three-class classifier for path references in the repo's documentation.

Why a naive existence check is wrong
------------------------------------
The documentation surface carries a few hundred path-shaped tokens. Requiring
every one of them to resolve against a clean checkout flags roughly two thirds
of the *correct* ones, because three different kinds of reference coexist and
only one of them is supposed to resolve:

``SOURCE``
    A fully-qualified repo path such as ``gridalyn/twin/core/graph.py``, or a
    ``../``-relative link resolved against the file that contains it. This is
    the only class that **must resolve**; one that does not is genuinely stale
    and is reported as a failure.

``SHORTHAND``
    A prefix-relative path that is correct as written. ``core/graph.py`` under
    the twin row of an architecture table means ``gridalyn/twin/core/graph.py``;
    ``platform/reports.py`` under the foundation row means
    ``gridalyn/foundation/platform/reports.py``; ``sdk/overview.md`` inside
    ``docs/`` means ``docs/sdk/overview.md``; ``scripts/config.py`` in a study
    write-up means ``projects/<study>/scripts/config.py``. The prefix set is
    **derived** (see :func:`_shorthand_prefixes`) from the layer packages under
    ``gridalyn/``, the study directories under ``projects/`` and ``docs/``, so
    adding a layer or a study does not silently go stale. Not a failure.

``RUNTIME``
    A path a clean checkout does not carry: produced by running a study, or
    living in a git-ignored tree. Recognised **structurally**, never by asking
    the filesystem, so the answer is identical on a clean checkout and on a
    working tree that has already run every study. The structural rule is:

    * any segment names a generated directory (``outputs``, ``cache``,
      ``site``, ``build``, ``_build``, ``generated``, ``dist``, ``public``,
      ``node_modules``, ``scratch``, ``__pycache__``, ``.pytest_cache``,
      ``.matplotlib``) -- every one of which carries zero git-tracked files in
      this repo, which is how the set was chosen rather than guessed; or
    * the first segment names a root git does not carry in full
      (``instances``, ``manuscripts``, ``datasets``); or
    * the leaf carries a bulk-artifact extension (``.parquet``, ``.npy``,
      ``.npz``, ``.h5``, ``.hdf5``); or
    * the first segment names an artifact sub-directory of a study's
      ``outputs/`` (``json``, ``reports``, ``data``, ``figures``, ``manifests``,
      ``scenarios``, ``timeseries``, ``models``, ``digital_twin``, ``semantic``)
      **and** the leaf is an artifact file -- this is how
      ``scenarios/S*_device_registry.parquet`` and ``json/aggregate_kpis.json``
      are recognised. The leaf condition is required, not optional: several of
      those names are also real package directories, so a bare ``semantic/``
      under the twin row is SHORTHAND for ``gridalyn/twin/semantic/`` and must
      not be swallowed by this rule.

    Not a failure, and never existence-checked.

Anything that matches none of the three is ``UNCLASSIFIED`` and **fails**.
Silence is not a class: a reference the taxonomy cannot place is a hole in the
taxonomy, and it is reported with its file and line rather than absorbed.

Order matters. ``RUNTIME`` is decided first, before any filesystem lookup,
precisely because this working tree *does* contain ``instances/``, ``cache/``
and ``projects/*/outputs/`` while CI's checkout does not. Classifying by
existence first would make the tool answer differently in the two places.

What counts as a path reference
-------------------------------
Only tokens inside a markdown inline-code span (`` `like/this` ``) or a
markdown link target (``[text](like/this)``). Prose is not scanned: an
unquoted path in a sentence cannot be told from an ordinary word.

**Fenced code blocks are excluded**, uniformly. Their contents are shell
commands, Python snippets and illustrative directory trees rather than claims
about where a file lives, and the same string inside a fence is routinely an
example rather than a reference. The count of code-span tokens skipped for
living in a fence is reported as a measured blind spot rather than left
implicit.

Explicitly excluded, and counted so the exclusions are visible:

* URLs -- anything containing ``://`` or whose first segment is a hostname
  (a dotted name ending in a known TLD), e.g. ``github.com/lirei-lab/gridalyn``.
* Absolute paths (``/home/...``) and ``~``-relative paths: not repo references.
* Shell fragments and prose/maths -- any token containing whitespace or one of
  ``()[]{}|$\\"'!?^%&;=`` (braces excluded only after brace expansion) or a
  non-ASCII character.
* npm scopes (``@duckdb/duckdb-wasm``).
* Bare names with no ``/`` at all (``model_inputs.py``, ``pyproject.toml``,
  ``CALIBRATION.md``). A dotted module path (``gridalyn.projects.api``) is a
  bare name too, so this exclusion removes both. These are name mentions, not
  path references; including them would swamp the real signal with every
  module named in prose. Their count is reported.

Notation handled rather than rejected:

* ``path.py:41`` and ``path.py::symbol`` -- the trailing line number or symbol
  is stripped.
* ``{a,b,c}`` brace enumeration -- expanded; **every** alternative must resolve.
* ``<name>`` placeholders -- replaced by ``*`` and matched by globbing.
* ``...`` elision -- treated as ``**``; a trailing ``...`` is dropped.
* Globs (``*.pkl``, ``S*_*.parquet``, ``docs/**``) -- matched by globbing, never
  by literal existence.

Exit status is 0 when no reference is stale and none is unclassified, else 1
with one located ``path:line: message`` per finding.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# --------------------------------------------------------------------------
# Classes
# --------------------------------------------------------------------------
SOURCE = "SOURCE"
SHORTHAND = "SHORTHAND"
RUNTIME = "RUNTIME"
UNCLASSIFIED = "UNCLASSIFIED"

CLASSES: tuple[str, ...] = (SOURCE, SHORTHAND, RUNTIME, UNCLASSIFIED)

# --------------------------------------------------------------------------
# Documentation surface
# --------------------------------------------------------------------------
# Built by walking the filesystem, never from ``git ls-files``: CLAUDE.md and
# AGENTS.md are git-ignored and would vanish from a tracked-files listing.
_ROOT_DOCS: tuple[str, ...] = (
    "CLAUDE.md",
    "AGENTS.md",
    "README.md",
    "CONTRIBUTING.md",
)
_DOCS_DIR = "docs"

# --------------------------------------------------------------------------
# RUNTIME structural rule
# --------------------------------------------------------------------------
_GENERATED_SEGMENTS: frozenset[str] = frozenset(
    {
        "outputs",
        "cache",
        "site",
        "build",
        "_build",
        "generated",
        "dist",
        "public",
        "node_modules",
        "scratch",
        "__pycache__",
        ".pytest_cache",
        ".matplotlib",
    }
)
# Roots git does not carry in full, so a clean checkout has nothing to resolve
# against. ``instances/`` is partially tracked (manifests yes, parquet no), which
# is exactly why it cannot be existence-checked either.
_UNCARRIED_ROOTS: frozenset[str] = frozenset({"instances", "manuscripts", "datasets"})
_ARTIFACT_EXTENSIONS: frozenset[str] = frozenset(
    {".parquet", ".npy", ".npz", ".h5", ".hdf5"}
)
# Sub-directories of a study's ``outputs/`` or of an instance's digital twin,
# routinely referenced without their parent. ``baselines`` is deliberately absent:
# baselines are tracked, so ``baselines/results_baseline.json`` is SHORTHAND.
_ARTIFACT_DIRS: frozenset[str] = frozenset(
    {
        "json",
        "reports",
        "data",
        "figures",
        "manifests",
        "scenarios",
        "timeseries",
        "models",
        "digital_twin",
        "semantic",
        # instances/<name>/digital_twin/base/ -- the twin's own model-version
        # lineage directory, named bare as ``base/metadata.json``.
        "base",
    }
)
_ARTIFACT_LEAF_EXTENSIONS: frozenset[str] = frozenset(
    {".json", ".csv", ".png", ".pdf", ".txt", ".parquet", ".npy", ".npz"}
)

# --------------------------------------------------------------------------
# Token exclusion
# --------------------------------------------------------------------------
_FORBIDDEN_CHARS = set("()[]|$\\\"'!?^%&;=`")
_KNOWN_TLDS: frozenset[str] = frozenset(
    {"com", "org", "net", "io", "ca", "gov", "edu", "dev", "ai", "co", "uk"}
)

_EXCLUDED_URL = "url"
_EXCLUDED_ABSOLUTE = "absolute-or-home path"
_EXCLUDED_FRAGMENT = "shell fragment or prose"
_EXCLUDED_SCOPE = "npm scope"
_EXCLUDED_BARE = "bare name (no '/')"


@dataclass(frozen=True)
class Reference:
    """One path reference found in the documentation.

    Attributes:
        file: Repo-relative path of the document it was found in.
        line: 1-indexed line number.
        raw: The token exactly as written.
        path: The token after notation normalisation.
    """

    file: str
    line: int
    raw: str
    path: str


@dataclass(frozen=True)
class Finding:
    """A classified reference plus the reason its class was chosen."""

    reference: Reference
    label: str
    detail: str

    def located(self) -> str:
        """Return a ``path:line: message`` line naming the reference."""
        return (
            f"{self.reference.file}:{self.reference.line}: "
            f"{self.label}: {self.reference.raw!r} -- {self.detail}"
        )


@dataclass(frozen=True)
class ScanReport:
    """Aggregate result of classifying the whole documentation surface."""

    findings: tuple[Finding, ...]
    stale: tuple[Finding, ...]
    unclassified: tuple[Finding, ...]
    files_scanned: int
    files_with_references: int
    skipped_in_fences: int
    skipped_bare_names: int
    excluded: tuple[tuple[str, int], ...]
    naive_failures: tuple[Finding, ...]

    def counts(self) -> dict[str, int]:
        """Return the per-class occurrence counts, zero-filled."""
        tally = Counter(finding.label for finding in self.findings)
        return {label: tally.get(label, 0) for label in CLASSES}

    def files_with_findings(self) -> int:
        """Return how many documents carry a stale or unclassified reference."""
        return len(
            {f.reference.file for f in tuple(self.stale) + tuple(self.unclassified)}
        )

    def naive_false_alarms(self) -> tuple[Finding, ...]:
        """Return references a naive existence check flags that are correct.

        These are the references that do not literally exist at the repo root
        yet are written correctly -- prefix-relative shorthand, runtime
        artifacts, and ``../`` links resolved against their own document. Their
        number is the entire reason this tool classifies instead of stat-ing.
        """
        wrong = {id(f) for f in tuple(self.stale) + tuple(self.unclassified)}
        return tuple(f for f in self.naive_failures if id(f) not in wrong)


# --------------------------------------------------------------------------
# Prefix derivation
# --------------------------------------------------------------------------
def _package_layers(root: Path) -> list[str]:
    """Return the layer package names directly under ``gridalyn/``.

    Derived rather than hardcoded: a hardcoded list goes stale the moment a
    layer is added or renamed. A directory counts as a layer when it holds an
    ``__init__.py``.
    """
    package = root / "gridalyn"
    if not package.is_dir():
        return []
    return sorted(
        child.name
        for child in package.iterdir()
        if child.is_dir() and (child / "__init__.py").is_file()
    )


def _shorthand_prefixes(root: Path) -> tuple[str, ...]:
    """Return every prefix a SHORTHAND reference may be written relative to.

    Three families, all derived from the tree:

    1. ``gridalyn/`` and ``gridalyn/<layer>/`` -- the architecture tables write
       module paths relative to the layer row they sit in.
    2. ``docs/`` -- documentation cross-links routinely omit it.
    3. ``projects/<study>/`` -- study write-ups write ``scripts/config.py`` and
       ``baselines/results_baseline.json`` relative to their own directory.
    4. ``projects/`` -- cross-study write-ups cannot be relative to any one
       study, so they name it: ``<study>/scripts/generate_x.py``. Symmetric
       with family 1, where ``gridalyn/`` covers ``<layer>/module.py``.
    """
    prefixes = ["gridalyn"]
    prefixes += [f"gridalyn/{layer}" for layer in _package_layers(root)]
    if (root / _DOCS_DIR).is_dir():
        prefixes.append(_DOCS_DIR)
    studies = root / "projects"
    if studies.is_dir():
        prefixes.append("projects")
        prefixes += sorted(
            f"projects/{child.name}"
            for child in studies.iterdir()
            if child.is_dir() and child.name != "__pycache__"
        )
    return tuple(prefixes)


def _top_level_entries(root: Path) -> frozenset[str]:
    """Return the names of everything directly inside the repo root."""
    return frozenset(child.name for child in root.iterdir())


# --------------------------------------------------------------------------
# Extraction
# --------------------------------------------------------------------------
def _document_files(root: Path) -> list[Path]:
    """Return the documentation surface, walked from disk not from git."""
    files = [root / name for name in _ROOT_DOCS]
    docs = root / _DOCS_DIR
    if docs.is_dir():
        files += sorted(docs.rglob("*.md"))
    return [path for path in files if path.is_file()]


def _code_spans(line: str) -> list[str]:
    """Return the contents of every backtick code span on one line."""
    spans: list[str] = []
    index = 0
    while True:
        start = line.find("`", index)
        if start == -1:
            return spans
        ticks = 0
        while start + ticks < len(line) and line[start + ticks] == "`":
            ticks += 1
        fence = "`" * ticks
        end = line.find(fence, start + ticks)
        if end == -1:
            return spans
        spans.append(line[start + ticks : end])
        index = end + ticks


def _link_targets(line: str) -> list[str]:
    """Return the target of every ``[text](target)`` markdown link on a line."""
    targets: list[str] = []
    index = 0
    while True:
        open_bracket = line.find("](", index)
        if open_bracket == -1:
            return targets
        close = line.find(")", open_bracket + 2)
        if close == -1:
            return targets
        targets.append(line[open_bracket + 2 : close].strip())
        index = close + 1


def _fenced_path_tokens(line: str) -> int:
    """Count path-shaped bare words on one line inside a fenced block.

    Fenced content is plain text, not code spans, so the blind spot has to be
    measured on whitespace-split words: counting code spans inside a fence would
    report a near-zero figure and understate what is being skipped.
    """
    return sum(
        1
        for word in line.split()
        if "/" in word and _exclusion_reason(_normalise(word.strip("*_,;"))) is None
    )


def _iter_document_tokens(text: str) -> tuple[list[tuple[int, str]], int]:
    """Return ``(line, token)`` pairs outside fences, plus the fenced-token count.

    Fenced blocks are skipped whole. The path-shaped words they would have
    contributed are counted so the deliberate blind spot is measured rather
    than implied.
    """
    tokens: list[tuple[int, str]] = []
    fenced = 0
    in_fence = False
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            fenced += _fenced_path_tokens(line)
            continue
        found = [span.strip() for span in _code_spans(line)]
        found += _link_targets(line)
        tokens += [(number, token) for token in found if token]
    return tokens, fenced


# --------------------------------------------------------------------------
# Normalisation and exclusion
# --------------------------------------------------------------------------
def _normalise(token: str) -> str:
    """Strip notation that decorates a path without being part of it."""
    path = token.split("#", 1)[0].strip()
    if "::" in path:
        path = path.split("::", 1)[0]
    head, sep, tail = path.rpartition(":")
    if sep and head and "/" not in tail and "//" not in path:
        path = head
    return path.strip()


def _looks_like_host(segment: str) -> bool:
    """Return True when a first path segment is really a hostname."""
    if "." not in segment:
        return False
    return segment.rsplit(".", 1)[-1].lower() in _KNOWN_TLDS


def _exclusion_reason(path: str) -> str | None:
    """Return why a token is not a path reference, or ``None`` if it is one."""
    if not path or path == "/":
        return _EXCLUDED_FRAGMENT
    if path.startswith("@"):
        return _EXCLUDED_SCOPE
    if "://" in path:
        return _EXCLUDED_URL
    if path.startswith("/") or path.startswith("~"):
        return _EXCLUDED_ABSOLUTE
    if any(character.isspace() for character in path):
        return _EXCLUDED_FRAGMENT
    if any(character in _FORBIDDEN_CHARS for character in path):
        return _EXCLUDED_FRAGMENT
    if not path.isascii():
        return _EXCLUDED_FRAGMENT
    if "/" not in path:
        return _EXCLUDED_BARE
    if _looks_like_host(path.split("/", 1)[0]):
        return _EXCLUDED_URL
    return None


# --------------------------------------------------------------------------
# Pattern expansion and resolution
# --------------------------------------------------------------------------
def _expand_braces(pattern: str) -> list[str]:
    """Expand one level of ``{a,b,c}`` enumeration into concrete patterns."""
    start = pattern.find("{")
    if start == -1:
        return [pattern]
    end = pattern.find("}", start)
    if end == -1:
        return [pattern.replace("{", "")]
    head, body, tail = pattern[:start], pattern[start + 1 : end], pattern[end + 1 :]
    expanded: list[str] = []
    for option in body.split(","):
        expanded += _expand_braces(f"{head}{option.strip()}{tail}")
    return expanded


def _expand_placeholders(path: str) -> str:
    """Replace ``<name>`` placeholders and ``...`` elisions with glob magic."""
    out: list[str] = []
    index = 0
    while index < len(path):
        if path[index] == "<":
            close = path.find(">", index)
            if close != -1:
                out.append("*")
                index = close + 1
                continue
        out.append(path[index])
        index += 1
    joined = "".join(out)
    segments = [segment for segment in joined.split("/") if segment != ""]
    segments = ["**" if segment == "..." else segment for segment in segments]
    while segments and segments[-1] == "**":
        segments.pop()
    return "/".join(segments)


def _resolve_relative(path: str, document: str) -> str | None:
    """Resolve a ``./`` or ``../`` link against the document containing it."""
    base = Path(document).parent
    try:
        combined = (base / path).as_posix()
    except ValueError:  # pragma: no cover - Path never raises here today
        return None
    parts: list[str] = []
    for segment in combined.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if not parts:
                return None
            parts.pop()
            continue
        parts.append(segment)
    return "/".join(parts)


def _matches(pattern: str, base: Path) -> bool:
    """Return True when a pattern names something existing under ``base``."""
    if not pattern:
        return base.is_dir()
    if not any(character in pattern for character in "*?"):
        return (base / pattern).exists()
    try:
        return any(True for _ in base.glob(pattern))
    except (ValueError, NotImplementedError, OSError):
        return False


def _resolves(path: str, base: Path) -> bool:
    """Return True when every brace alternative of ``path`` exists under ``base``.

    Every alternative must resolve: ``adapters/{cim,geojson,network}.py``
    enumerates three real modules, so one missing member makes the reference
    wrong even though the other two are fine.
    """
    alternatives = _expand_braces(path)
    if not alternatives:
        return False
    return all(_matches(_expand_placeholders(one), base) for one in alternatives)


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------
def _segments(path: str) -> list[str]:
    """Return the non-empty segments of a normalised reference."""
    return [segment for segment in path.split("/") if segment not in ("", ".")]


def _runtime_reason(path: str) -> str | None:
    """Return why a reference is RUNTIME, structurally, or ``None``.

    Decided without touching the filesystem so the answer is the same on a
    clean checkout and on a tree that has already produced every artifact.
    """
    segments = _segments(path)
    if not segments:
        return None
    for segment in segments:
        base = segment.split("{", 1)[0]
        if base in _GENERATED_SEGMENTS:
            return f"generated directory segment {segment!r}"
    if segments[0] in _UNCARRIED_ROOTS:
        return f"git-ignored root {segments[0]!r}; a clean checkout has no such tree"
    suffix = Path(segments[-1]).suffix.lower()
    if suffix in _ARTIFACT_EXTENSIONS:
        return f"bulk-artifact extension {suffix!r}"
    if segments[0] in _ARTIFACT_DIRS and suffix in _ARTIFACT_LEAF_EXTENSIONS:
        return f"artifact {suffix!r} under outputs sub-directory {segments[0]!r}"
    return None


def _source_shaped(
    path: str, root: Path, top_level: frozenset[str], prefixes: tuple[str, ...]
) -> bool:
    """Return True when a reference claims a real location and simply misses.

    Either its first segment names something at the repo root, or it names a
    directory that exists under one of the shorthand prefixes -- a shorthand
    whose tail has gone stale, which is just as wrong as a stale full path.
    """
    segments = _segments(path)
    if not segments:
        return False
    head = segments[0].split("{", 1)[0]
    if head in top_level:
        return True
    return any((root / prefix / head).is_dir() for prefix in prefixes)


def _classify(
    reference: Reference,
    root: Path,
    prefixes: tuple[str, ...],
    top_level: frozenset[str],
) -> Finding:
    """Assign exactly one of the four labels to a reference."""
    runtime = _runtime_reason(reference.path)
    if runtime is not None:
        return Finding(reference, RUNTIME, runtime)

    target = reference.path
    if target.startswith("./") or target.startswith("../"):
        resolved = _resolve_relative(target, reference.file)
        if resolved is None:
            return Finding(reference, UNCLASSIFIED, "escapes the repository root")
        if _resolves(resolved, root):
            return Finding(reference, SOURCE, f"resolves as {resolved}")
        return Finding(reference, SOURCE, f"STALE: {resolved} does not exist")

    if _resolves(target, root):
        return Finding(reference, SOURCE, "resolves from the repo root")
    for prefix in prefixes:
        if _resolves(f"{prefix}/{target}", root):
            return Finding(reference, SHORTHAND, f"resolves under {prefix}/")
    if _source_shaped(target, root, top_level, prefixes):
        return Finding(reference, SOURCE, "STALE: no such path, and no prefix helps")
    return Finding(reference, UNCLASSIFIED, "matches no class")


def _is_stale(finding: Finding) -> bool:
    """Return True when a SOURCE finding failed to resolve."""
    return finding.label == SOURCE and finding.detail.startswith("STALE")


# --------------------------------------------------------------------------
# Scan
# --------------------------------------------------------------------------
def scan(root: Path = ROOT) -> ScanReport:
    """Classify every path reference across the documentation surface."""
    prefixes = _shorthand_prefixes(root)
    top_level = _top_level_entries(root)
    findings: list[Finding] = []
    excluded: Counter[str] = Counter()
    fenced = 0
    bare = 0
    files = _document_files(root)
    files_with_references = 0

    for path in files:
        relative = path.resolve().relative_to(root).as_posix()
        tokens, in_fence = _iter_document_tokens(path.read_text(encoding="utf-8"))
        fenced += in_fence
        before = len(findings)
        for number, token in tokens:
            normalised = _normalise(token)
            reason = _exclusion_reason(normalised)
            if reason == _EXCLUDED_BARE:
                bare += 1
                continue
            if reason is not None:
                excluded[reason] += 1
                continue
            reference = Reference(relative, number, token, normalised)
            findings.append(_classify(reference, root, prefixes, top_level))
        if len(findings) > before:
            files_with_references += 1

    return ScanReport(
        findings=tuple(findings),
        stale=tuple(f for f in findings if _is_stale(f)),
        unclassified=tuple(f for f in findings if f.label == UNCLASSIFIED),
        files_scanned=len(files),
        files_with_references=files_with_references,
        skipped_in_fences=fenced,
        skipped_bare_names=bare,
        excluded=tuple(sorted(excluded.items())),
        naive_failures=tuple(
            f for f in findings if not (root / f.reference.path).exists()
        ),
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _print_distribution(report: ScanReport) -> None:
    """Print the per-class distribution and the measured blind spots."""
    counts = report.counts()
    total = sum(counts.values())
    print(
        f"documentation surface: {report.files_scanned} files scanned, "
        f"{report.files_with_references} carrying references"
    )
    print(f"path references classified: {total}")
    for label in CLASSES:
        print(f"  {label:<14} {counts[label]:>5}")
    print(f"  {'(of SOURCE)':<14} {len(report.stale):>5} stale")
    print(
        f"genuinely wrong: {len(report.stale)} stale + "
        f"{len(report.unclassified)} unclassified across "
        f"{report.files_with_findings()} files"
    )
    print(
        f"a naive existence check would flag {len(report.naive_failures)}, of "
        f"which {len(report.naive_false_alarms())} are correct as written"
    )
    print("blind spots (deliberate, measured):")
    print(f"  {'fenced-block':<14} {report.skipped_in_fences:>5} tokens skipped")
    print(f"  {'bare-name':<14} {report.skipped_bare_names:>5} tokens skipped")
    for reason, count in report.excluded:
        print(f"  {reason:<14} {count:>5} tokens skipped")


def _print_prefixes(report_root: Path) -> None:
    """Print the derived SHORTHAND prefixes."""
    print("derived SHORTHAND prefixes:")
    for prefix in _shorthand_prefixes(report_root):
        print(f"  {prefix}/")


def _build_parser() -> argparse.ArgumentParser:
    """Return the argument parser for the classifier CLI."""
    parser = argparse.ArgumentParser(
        prog="check_doc_paths.py",
        description=(
            "Classify every documentation path reference as SOURCE (must "
            "resolve), SHORTHAND (prefix-relative, correct as written), "
            "RUNTIME (generated or git-ignored, correct as written) or "
            "UNCLASSIFIED (a hole in the taxonomy). Exits 1 on any stale "
            "SOURCE reference or any UNCLASSIFIED one."
        ),
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="print the per-class distribution and the measured blind spots",
    )
    parser.add_argument(
        "--list",
        choices=CLASSES,
        help="list every reference assigned the given class, with its location",
    )
    parser.add_argument(
        "--prefixes",
        action="store_true",
        help="print the SHORTHAND prefixes derived from the tree",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="repository root to scan (default: the repo this file lives in)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Scan, report, and return 0 when nothing is stale or unclassified."""
    args = _build_parser().parse_args(argv)
    root = args.root.resolve()
    if args.prefixes:
        _print_prefixes(root)
    report = scan(root)
    if args.report or args.prefixes:
        _print_distribution(report)
    if args.list:
        for finding in report.findings:
            if finding.label == args.list:
                print(finding.located())

    failures = list(report.stale) + list(report.unclassified)
    if failures:
        print(f"documentation path references FAILED ({len(failures)} finding(s)):")
        for finding in failures:
            print(f"  {finding.located()}")
        return 1
    print("documentation path references OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
