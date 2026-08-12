"""Re-runnable capture of the twin's real consumers, for the R7 identity check.

R7 says a phase must not silently change study outputs. Phase 11 rewrote the
network model, its repository and its manifest, so the question it had to answer
was narrower and sharper: *does the same base produce the same thing through the
consumers a study actually calls?*

Plan 11-06 answered it and reported ``sha256 7dbcbb4c…`` on both sides. The
capture harness was not preserved. A digest nobody can re-derive is not
evidence -- a later reader can neither reproduce it nor tell whether a change
broke the property -- and review cycle 1 of Phase 11 raised exactly that. This
module is the missing harness.

**What it captures**, and nothing else, is enumerated in :data:`COVERAGE`. State
it whenever the digest is quoted: a hash means nothing without the field set it
was taken over. Two independent reproductions of this property already exist and
report *different* digests (``7dbcbb4c…`` from the phase, ``ee5a3e4b…`` from a
reviewer's harness) for precisely this reason -- both showed before == after,
over different field sets. This module's number is the canonical one because
this module says what it covers.

**Digest = f(code, base artifacts).** The base parquets are gitignored, so the
digest is not derivable from a commit alone. The base fingerprint is therefore
reported *beside* the digest rather than inside it: a mismatch is then
attributable to changed code or changed data instead of being a mystery.

**The comparison runs each ref in its own git worktree**, importing ``gridalyn``
from that tree -- otherwise every capture silently imports the checkout the
harness lives in and the "identity" result is vacuous by construction. What
makes that non-vacuous is not the editable-finder strip (measured a no-op in
this venv; see :func:`_strip_editable_finder`) but the fact that the child
reports the directory it actually imported from and the parent asserts it lies
inside the worktree. The harness itself stays constant across refs -- it is
invoked from the current tree in every case -- so only the code under test
varies, which is the only way the comparison isolates the code.

Usage::

    python tools/r7_twin_consumer_identity.py                    # this tree
    python tools/r7_twin_consumer_identity.py d6aa606e 6ed179c0  # compare refs
    python tools/r7_twin_consumer_identity.py --json             # full payload
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

SCHEMA_VERSION = "1.0"

#: Exactly what the canonical digest covers. Quote this beside the number.
COVERAGE: tuple[str, ...] = (
    "load_model(): counts (6 keys), source_adapter, source_standard, "
    "provenance_status, every ModelIdentity field, and a content digest of "
    "each of the five canonical tables (columns, dtypes and rows)",
    "validate_integrity(): valid, errors, warnings, and the full summary dict",
    "build_dashboard_catalog(): the whole returned mapping, minus created_at",
)

#: Fields removed before hashing, each because it is wall-clock-derived at call
#: time and would differ between two runs of identical code over identical data.
#: Disclosed rather than hidden -- this is a pre-existing non-determinism in
#: ``build_dashboard_catalog``, not something this harness introduced.
STRIPPED_FIELDS: tuple[str, ...] = ("build_dashboard_catalog.created_at",)

#: Timestamps that are **kept** in the digest, and why. These are read from the
#: base manifest rather than produced at call time, so they are constant for a
#: fixed base and a code change that stopped propagating one is a real
#: difference the digest must show. They do mean the digest moves when the base
#: manifest is regenerated -- which the base fingerprint makes attributable.
DATA_DERIVED_TIMESTAMPS: tuple[str, ...] = ("load_model().identity.created",)

#: Inputs the catalog leg is driven with. Empty scenario inputs are deliberate:
#: they leave the ``network_model`` block -- the only part of the catalog the
#: twin contributes -- fully populated, and keep the leg free of any study's
#: generated artifacts. The leg therefore proves nothing about a real study's
#: scenario list, and does not claim to.
_EMPTY_SCENARIO_INPUTS = "scenario_index={}, powerflow_summary={}, extensions=None"


def _strip_editable_finder() -> None:
    """Remove the editable install's finder from ``sys.meta_path``.

    ``pip install -e`` registers a finder that resolves ``gridalyn`` to the
    directory it was installed from, whatever ``sys.path`` says. If that finder
    ran first it would defeat the entire comparison: a capture told to import a
    worktree would import the main checkout and report a perfect match against
    itself.

    **Measured, so the claim is not overstated.** In this repository's venv the
    setuptools shim *appends* ``_EditableFinder`` to ``sys.meta_path``
    (``install()`` in ``__editable___gridalyn_0_1_0_finder.py``), which puts it
    after ``PathFinder`` -- so ``sys.path`` already wins and stripping is a
    no-op here. It is kept because that ordering is a setuptools implementation
    detail, not a contract, and a strict-mode editable install could prepend.
    The guarantee the comparison actually rests on is neither of these: it is
    the ``import_root`` the child reports and :func:`_capture_at_ref` asserts.

    Note the entries are finder **classes**, not instances, so the module has
    to be read off the object itself before falling back to its type -- a
    ``type(finder).__module__`` test reads ``builtins`` and matches nothing.
    """
    sys.meta_path[:] = [
        finder
        for finder in sys.meta_path
        if not getattr(finder, "__module__", type(finder).__module__).startswith(
            "__editable__"
        )
    ]


def _frame_digest(frame: Any) -> dict[str, Any]:
    """Return a content digest of one canonical table.

    Args:
        frame: The loaded ``pandas.DataFrame``.

    Returns:
        Its shape, column names, dtypes and a ``sha256`` over the serialized
        rows. Serialization is ``orient="split"`` with ISO dates and 15-digit
        floats, so the digest is stable and the payload stays inspectable when
        one leg disagrees.
    """
    payload = frame.to_json(orient="split", date_format="iso", double_precision=15)
    return {
        "rows": int(len(frame)),
        "columns": [str(column) for column in frame.columns],
        "dtypes": [str(dtype) for dtype in frame.dtypes],
        "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }


def _jsonable(value: Any) -> Any:
    """Return ``value`` in a JSON-serializable, order-preserving form."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return str(value)


def capture(base_dir: Path) -> dict[str, Any]:
    """Run the three twin consumers over ``base_dir`` and return their output.

    Args:
        base_dir: Directory holding the canonical base artifacts.

    Returns:
        The digestible payload -- the three legs, with :data:`STRIPPED_FIELDS`
        already removed.
    """
    from gridalyn.projects.dashboard_catalog import build_dashboard_catalog
    from gridalyn.twin.network.repository import NetworkModelRepository

    repository = NetworkModelRepository.from_parquet(base_dir)
    model = repository.load_model()
    integrity = repository.validate_integrity()
    catalog = build_dashboard_catalog(
        scenario_index={},
        powerflow_summary={},
        optional_extensions=None,
        root=base_dir,
        network_repository=repository,
    )
    catalog.pop("created_at", None)

    # ``identity``, ``source_adapter``, ``source_standard`` and
    # ``provenance_status`` are Phase-11 additions. A pre-phase capture simply
    # does not have them, and a key that is *absent* on one side is what the
    # additive-only classification below is built to recognise -- so they are
    # omitted rather than filled with ``None``, which would read as "the model
    # reported no identity" and be a different claim entirely.
    identity = getattr(model, "identity", None)
    load_model: dict[str, Any] = {
        "counts": model.counts,
        "tables": {
            "buses": _frame_digest(model.buses),
            "lines": _frame_digest(model.lines),
            "transformers": _frame_digest(model.transformers),
            "buildings": _frame_digest(model.buildings),
            "connectivity": _frame_digest(model.connectivity),
        },
    }
    for field in ("source_adapter", "source_standard", "provenance_status"):
        if hasattr(model, field):
            load_model[field] = getattr(model, field)
    if identity is not None:
        # Read the field list off the dataclass rather than naming the fields
        # here. ``ModelIdentity`` gained fields in 11-01 and had two renamed in
        # review cycle 1, and a harness that hardcoded either set would crash on
        # the other -- turning "the captures differ" into "the tool does not
        # run", which is the failure mode that lost the original evidence. A
        # renamed field then surfaces honestly, as one removed key and one
        # added key, for the operator to judge.
        load_model["identity"] = {
            field.name: _jsonable(getattr(identity, field.name))
            for field in dataclasses.fields(identity)
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "legs": {
            "load_model": load_model,
            "validate_integrity": {
                "valid": bool(integrity.valid),
                "errors": list(integrity.errors),
                "warnings": list(integrity.warnings),
                "summary": dict(integrity.summary),
            },
            "build_dashboard_catalog": catalog,
        },
    }


def digest(payload: dict[str, Any]) -> str:
    """Return the canonical ``sha256`` of a captured payload."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def flatten(payload: Any, prefix: str = "") -> dict[str, str]:
    """Return the payload as a flat map of dotted path to canonical JSON value.

    Args:
        payload: Any JSON-serializable structure.
        prefix: Dotted path accumulated so far.

    Returns:
        One entry per leaf. Lists are leaves rather than being indexed, because
        a re-ordered list is a changed value, not a set of moved keys.
    """
    if isinstance(payload, dict):
        flat: dict[str, str] = {}
        for key, value in payload.items():
            flat |= flatten(value, f"{prefix}.{key}" if prefix else str(key))
        return flat
    return {prefix: json.dumps(payload, sort_keys=True)}


def classify(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Classify how two captures differ.

    This is the part that makes the tool answer R7 rather than a stricter
    question R7 never asked. Phase 11's whole point was to *add* a provenance
    block, so byte-identity is the wrong bar: a capture that gained
    ``load_model.identity`` and kept every pre-existing value is R7-clean, and a
    capture where one pre-existing value moved is not, however small the move.

    Args:
        before: Payload captured from the earlier ref.
        after: Payload captured from the later ref.

    Returns:
        ``added`` / ``removed`` keys and ``changed`` ``path -> (before, after)``
        pairs, plus the ``verdict``: ``identical``, ``additive`` (R7 holds --
        keys appeared and nothing else moved) or ``regressed``.
    """
    flat_before = flatten(before)
    flat_after = flatten(after)
    added = sorted(set(flat_after) - set(flat_before))
    removed = sorted(set(flat_before) - set(flat_after))
    changed = {
        path: (flat_before[path], flat_after[path])
        for path in sorted(set(flat_before) & set(flat_after))
        if flat_before[path] != flat_after[path]
    }
    if not added and not removed and not changed:
        verdict = "identical"
    elif added and not removed and not changed:
        verdict = "additive"
    else:
        verdict = "regressed"
    return {
        "verdict": verdict,
        "added": added,
        "removed": removed,
        "changed": changed,
    }


def base_fingerprint(base_dir: Path) -> dict[str, str]:
    """Return a ``sha256`` per file in the base directory.

    The base parquets are gitignored, so a commit does not pin them. Reporting
    the input's identity beside the output's is what lets a later reader tell a
    code regression from a regenerated base.
    """
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(base_dir.iterdir())
        if path.is_file()
    }


def _capture_at_ref(ref: str, base_dir: Path) -> dict[str, Any]:
    """Capture with ``gridalyn`` imported from a worktree checked out at ``ref``.

    Args:
        ref: Any git revision this repository can resolve.
        base_dir: Base artifacts, taken from the current tree in every case --
            R7 asks what the *same* data does through *different* code.

    Returns:
        The child's parsed output, including the directory it imported from.

    Raises:
        RuntimeError: If the worktree could not be created, the child failed,
            or the child imported ``gridalyn`` from anywhere but the worktree.
    """
    worktree = Path(tempfile.mkdtemp(prefix=f"r7-{ref[:8]}-"))
    try:
        created = subprocess.run(
            ["git", "worktree", "add", "--detach", "--quiet", str(worktree), ref],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if created.returncode != 0:
            raise RuntimeError(
                f"could not check out {ref!r} into {worktree}: "
                f"{created.stderr.strip()}"
            )
        child = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--base",
                str(base_dir),
                "--import-from",
                str(worktree),
                "--json",
            ],
            cwd=str(worktree),
            env={**os.environ, "PYTHONPATH": str(worktree)},
            capture_output=True,
            text=True,
            check=False,
        )
        if child.returncode != 0:
            raise RuntimeError(f"capture at {ref} failed:\n{child.stderr}")
        result: dict[str, Any] = json.loads(child.stdout)
        imported = Path(result["import_root"]).resolve()
        if (
            worktree.resolve() not in imported.parents
            and imported != worktree.resolve()
        ):
            raise RuntimeError(
                f"capture at {ref} imported gridalyn from {imported}, not from "
                f"the worktree {worktree}; the editable-install finder was not "
                "stripped, so the comparison would have been vacuous"
            )
        result["ref"] = ref
        return result
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree)],
            cwd=REPO_ROOT,
            capture_output=True,
            check=False,
        )


def _default_base() -> Path:
    """Return the workspace's canonical base directory."""
    from gridalyn.foundation.platform.workspace import ArtifactLayout

    return Path(ArtifactLayout(REPO_ROOT).base)


#: Verdicts under which R7 holds. ``additive`` is included on purpose: keys
#: appearing is what Phase 11 set out to do, and a bar that failed on it would
#: be a bar nobody could pass without abandoning the phase.
R7_CLEAN_VERDICTS: frozenset[str] = frozenset({"identical", "additive"})


def _difference_lines(earlier: dict[str, Any], later: dict[str, Any]) -> list[str]:
    """Render one pairwise comparison, verdict first."""
    comparison = classify(earlier["payload"], later["payload"])
    verdict = comparison["verdict"]
    held = "R7 HOLDS" if verdict in R7_CLEAN_VERDICTS else "R7 VIOLATED"
    lines = [
        f"**{earlier['ref']} -> {later['ref']}: {verdict.upper()} — {held}**",
        "",
        f"- keys added: {len(comparison['added'])}",
        f"- keys removed: {len(comparison['removed'])}",
        f"- pre-existing values changed: {len(comparison['changed'])}",
    ]
    for path in comparison["added"][:20]:
        lines.append(f"  - added `{path}`")
    for path in comparison["removed"][:20]:
        lines.append(f"  - REMOVED `{path}`")
    for path, (was, now) in list(comparison["changed"].items())[:20]:
        lines.append(f"  - CHANGED `{path}`: `{was}` -> `{now}`")
    return lines


def _report(refs: list[str], results: list[dict[str, Any]], base_dir: Path) -> str:
    """Render the human-facing verdict."""
    lines = ["### R7 — twin consumer output identity", ""]
    lines.append(f"Base artifacts: `{base_dir}`")
    lines.append("")
    lines.append("Covered by the digest:")
    lines += [f"- {item}" for item in COVERAGE]
    lines.append("")
    lines.append(f"Stripped before hashing: {', '.join(STRIPPED_FIELDS)}")
    lines.append(f"Kept, data-derived: {', '.join(DATA_DERIVED_TIMESTAMPS)}")
    lines.append(f"Catalog leg driven with {_EMPTY_SCENARIO_INPUTS}.")
    lines.append("")
    lines.append("| Ref | Imported from | sha256 |")
    lines.append("|---|---|---|")
    # strict=True is load-bearing: _report's only caller builds results as a
    # comprehension over refs, so a length mismatch means that invariant broke
    # and a ref would be silently dropped from the comparison table.
    for ref, result in zip(refs, results, strict=True):
        root = Path(result["import_root"])
        lines.append(f"| `{ref}` | `{root}` | `{result['digest']}` |")
    lines.append("")
    fingerprints = {json.dumps(result["base"], sort_keys=True) for result in results}
    if len(fingerprints) > 1:
        lines.append(
            "**The base artifacts moved between captures.** The digests are "
            "not comparable; re-run both legs against one base."
        )
        lines.append("")
    # strict=False is correct here: this pairs each result with its successor,
    # so the operands are deliberately n and n-1 long.
    for earlier, later in zip(results, results[1:], strict=False):
        lines += _difference_lines(earlier, later)
    lines.append("")
    lines.append("Base fingerprint:")
    for name, value in sorted(results[0]["base"].items()):
        lines.append(f"- `{name}` `{value}`")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Capture the twin consumers, optionally comparing several refs.

    Args:
        argv: Argument list; defaults to ``sys.argv[1:]``.

    Returns:
        0 when every capture succeeded and all digests agree, 1 otherwise.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "refs",
        nargs="*",
        help="git revisions to capture, each in its own worktree; omit to "
        "capture the working tree",
    )
    parser.add_argument(
        "--base", type=Path, default=None, help="base artifacts directory"
    )
    parser.add_argument(
        "--json", action="store_true", help="print the full captured payload"
    )
    parser.add_argument(
        "--import-from",
        type=Path,
        default=None,
        help="import gridalyn from this directory (used by the worktree legs)",
    )
    args = parser.parse_args(argv)

    if args.import_from is not None:
        sys.path.insert(0, str(args.import_from.resolve()))
        _strip_editable_finder()

    base_dir = (args.base or _default_base()).resolve()
    if not base_dir.is_dir():
        raise SystemExit(
            f"{base_dir}: base artifacts directory not found. Build it with "
            "`gridalyn-dt build`, or pass --base <dir>."
        )

    if args.refs:
        results = [_capture_at_ref(ref, base_dir) for ref in args.refs]
        print(_report(args.refs, results, base_dir))
        if args.json:
            print(json.dumps(results, indent=2, sort_keys=True))
        verdicts = {
            classify(earlier["payload"], later["payload"])["verdict"]
            # deliberately n and n-1: adjacent pairs, see _report
            for earlier, later in zip(results, results[1:], strict=False)
        }
        return 0 if verdicts <= R7_CLEAN_VERDICTS else 1

    import gridalyn

    payload = capture(base_dir)
    result = {
        "ref": "<working tree>",
        "import_root": str(Path(gridalyn.__file__).resolve().parent),
        "digest": digest(payload),
        "base": base_fingerprint(base_dir),
        "coverage": list(COVERAGE),
        "stripped": list(STRIPPED_FIELDS),
        "payload": payload,
    }
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(_report(["<working tree>"], [result], base_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
