"""Account for the verification work CI cannot do.

Some of this repository's verification is real, expensive and impossible to
run on a hosted runner: regenerating the flagship study takes about six hours,
and executing every documented instruction needs clean environments, a network
and a node runtime. Until now those protocols were tracked in prose -- a
sentence in a document saying an operator had run something, with nothing
tying the claim to a tree.

This module makes that claim checkable. A receipt records WHAT was run, AT
WHICH COMMIT, and WHAT CAME OUT. The gate then asks three questions that prose
cannot answer:

* is every protocol we say is operator-verified actually declared here?
* is each receipt complete -- command, result and evidence, not a bare "ok"?
* does the commit it names really exist in this history and lead to HEAD?

That last one is what stops a receipt being a wish. You cannot claim a run at
a commit that never existed, or one from a branch that was thrown away.

**What a receipt is not.** It is not a substitute for running something CI
could run itself. A receipt asserts; a test proves. On 2026-08-06 a local
suite passed and CI caught a real failure the local tree could not see,
because two stale copies of a deleted package were still on disk -- a receipt
would have said "green" and been wrong. So receipts are used here only where
the alternative is *no verification at all*, never to replace a job.

**Staleness is reported, not enforced.** A protocol whose watched paths have
moved since its receipt is out of date, and the tool says so loudly. It does
not fail the build: a gate that demands a six-hour run before every merge is a
gate that gets switched off, which is how the mypy ratchet came to report
rather than demand zero.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
RECEIPTS_PATH = REPO_ROOT / "docs" / "development" / "verification-receipts.json"

SCHEMA_VERSION = "1.0"

#: Protocols that must be accounted for. Adding a protocol here without a
#: receipt fails the gate, so an operator-only claim cannot be introduced in
#: prose and then quietly forgotten.
REQUIRED_PROTOCOLS: tuple[str, ...] = (
    "flagship-reproduce",
    "flagship-subset",
    "docs-instruction-sweep",
    "subprocess-coverage",
)

#: Fields every receipt carries, whatever its status.
_COMMON_FIELDS: tuple[str, ...] = ("status", "command", "watched", "rationale")

#: Additional fields a receipt must carry once it claims a real run.
_RECORDED_FIELDS: tuple[str, ...] = ("commit", "recorded_on", "result", "evidence")

_STATUSES: tuple[str, ...] = ("recorded", "deferred")

#: Outcomes a per-stage record may claim.
_STAGE_STATUSES: tuple[str, ...] = ("ok", "skipped", "failed")


@dataclass(frozen=True)
class Finding:
    """One problem with the receipt ledger.

    Attributes:
        protocol: Protocol the finding belongs to, or ``"<ledger>"``.
        kind: Short machine-readable category.
        detail: Located, remediating description.
    """

    protocol: str
    kind: str
    detail: str

    def located(self) -> str:
        """Return the finding as a single reportable line."""
        return f"{self.protocol}: {self.kind}: {self.detail}"


def load_receipts(path: Path = RECEIPTS_PATH) -> dict[str, Any]:
    """Read the receipt ledger.

    Args:
        path: Ledger location; defaults to the tracked file.

    Returns:
        The parsed ledger.

    Raises:
        FileNotFoundError: If the ledger is missing, naming how to create it.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"{path}: verification receipt ledger not found. It is a tracked "
            f"file; restore it from git, or author it with the schema "
            f"documented in {Path(__file__).relative_to(REPO_ROOT)}"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _git(*args: str) -> tuple[int, str]:
    """Run a git command in the repository, returning exit code and output."""
    completed = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode, completed.stdout.strip()


def repository_is_shallow() -> bool:
    """Return True when this checkout carries a truncated history.

    ``actions/checkout`` clones at depth 1 unless told otherwise, and a
    truncated history cannot answer an ancestry question about any commit but
    its own tip.
    """
    _code, out = _git("rev-parse", "--is-shallow-repository")
    return out.strip() == "true"


def _commit_is_in_history(commit: str) -> bool:
    """Return True when ``commit`` exists and is an ancestor of HEAD.

    A receipt naming a commit outside this history is either fabricated or
    recorded on a branch that was discarded; either way it vouches for a tree
    nobody can inspect.

    Callers must consult :func:`repository_is_shallow` first: on a truncated
    clone this returns False for every commit but the tip, which is absence of
    evidence and not evidence of absence. Conflating the two turned a green
    gate red on a legitimate receipt the first time this ran in CI.
    """
    exists, _ = _git("cat-file", "-e", f"{commit}^{{commit}}")
    if exists != 0:
        return False
    ancestor, _ = _git("merge-base", "--is-ancestor", commit, "HEAD")
    return ancestor == 0


def changed_since(commit: str, watched: list[str]) -> list[str]:
    """Return the watched paths that changed between ``commit`` and HEAD.

    Args:
        commit: Commit the receipt was recorded at.
        watched: Path prefixes whose movement invalidates the receipt.

    Returns:
        Sorted changed paths, empty when the receipt is still current.
    """
    if not watched:
        return []
    code, out = _git("diff", "--name-only", f"{commit}...HEAD", "--", *watched)
    if code != 0:
        return []
    return sorted(line for line in out.splitlines() if line)


def audit(ledger: dict[str, Any]) -> tuple[list[Finding], list[str]]:
    """Check the ledger and compute which receipts have gone stale.

    Args:
        ledger: Parsed receipt ledger.

    Returns:
        A ``(findings, stale)`` pair. ``findings`` are failures; ``stale`` is
        the reported-not-enforced list of protocols whose watched paths moved.
    """
    findings: list[Finding] = []
    stale: list[str] = []

    if ledger.get("schema_version") != SCHEMA_VERSION:
        findings.append(
            Finding(
                "<ledger>",
                "schema",
                f"schema_version must be {SCHEMA_VERSION!r}, found "
                f"{ledger.get('schema_version')!r}",
            )
        )

    receipts = ledger.get("receipts")
    if not isinstance(receipts, dict):
        findings.append(Finding("<ledger>", "schema", "'receipts' must be a mapping"))
        return findings, stale

    missing = [name for name in REQUIRED_PROTOCOLS if name not in receipts]
    for name in missing:
        findings.append(
            Finding(
                name,
                "undeclared",
                "listed in REQUIRED_PROTOCOLS but has no receipt; add an entry "
                "to the ledger recording the run, or drop it from the required "
                "set if it is no longer operator-verified",
            )
        )

    extra = sorted(set(receipts) - set(REQUIRED_PROTOCOLS))
    for name in extra:
        findings.append(
            Finding(
                name,
                "unknown",
                "has a receipt but is not in REQUIRED_PROTOCOLS; add it there "
                "so the gate keeps asking about it, or remove the receipt",
            )
        )

    for name in sorted(set(receipts) & set(REQUIRED_PROTOCOLS)):
        findings.extend(_audit_one(name, receipts[name], stale))

    return findings, stale


def _shape_problems(name: str, receipt: dict[str, Any]) -> list[Finding]:
    """Return the problems every receipt can have, whatever its status."""
    findings = [
        Finding(name, "incomplete", f"{field!r} is empty")
        for field in _COMMON_FIELDS
        if field != "watched" and not str(receipt.get(field) or "").strip()
    ]
    if not isinstance(receipt.get("watched"), list):
        findings.append(
            Finding(name, "schema", "'watched' must be a list of path prefixes")
        )
    if receipt.get("status") not in _STATUSES:
        findings.append(
            Finding(
                name,
                "schema",
                f"status {receipt.get('status')!r} is not one of "
                f"{', '.join(_STATUSES)}",
            )
        )
    return findings


def _recorded_problems(
    name: str, receipt: dict[str, Any], stale: list[str]
) -> list[Finding]:
    """Return the problems specific to a receipt claiming a real run."""
    findings = [
        Finding(
            name,
            "incomplete",
            f"{field!r} is empty, but status is 'recorded' -- a receipt that "
            "claims a run must say when, at which commit, and what came out",
        )
        for field in _RECORDED_FIELDS
        if not str(receipt.get(field) or "").strip()
    ]
    commit = str(receipt.get("commit") or "").strip()
    if not commit:
        return findings
    if repository_is_shallow():
        # A depth-1 checkout knows only its own tip, so it can neither confirm
        # nor refute any other commit. Reporting "fabricated" here would be a
        # claim the checkout is not entitled to make -- and it made exactly
        # that claim about four legitimate receipts the first time this gate
        # ran under `actions/checkout`, whose default depth is 1. The job that
        # is meant to enforce this rule therefore fetches full history; see
        # `fetch-depth: 0` in .github/workflows/ci.yml.
        return findings
    if not _commit_is_in_history(commit):
        findings.append(
            Finding(
                name,
                "unverifiable-commit",
                f"commit {commit} is not an ancestor of HEAD in this "
                "repository, so the tree it vouches for cannot be inspected; "
                "re-record the protocol at a commit that is",
            )
        )
    elif changed_since(commit, list(receipt.get("watched") or [])):
        stale.append(name)
    return findings


def _stages_problems(name: str, stages: Any) -> list[Finding]:
    """Return the problems an optional per-stage record list can have.

    ``stages`` is optional and never required; when present it must be a list
    of mappings, each carrying a non-empty ``name`` and ``status`` (the
    per-stage outcome — ``ok``, ``skipped`` or ``failed``), and any per-stage
    ``commit`` must name a commit that exists in this history and leads to
    HEAD (the same anti-forgery rule the top-level commit obeys).

    Args:
        name: Protocol the stages belong to.
        stages: The parsed ``stages`` value, or ``None`` when absent.

    Returns:
        Findings describing any malformed or unverifiable stage records.
    """
    if stages is None:
        return []
    if not isinstance(stages, list):
        return [Finding(name, "schema", "'stages' must be a list of stage records")]
    findings: list[Finding] = []
    for index, stage in enumerate(stages):
        where = f"stages[{index}]"
        if not isinstance(stage, dict):
            findings.append(Finding(name, "schema", f"{where} must be a mapping"))
            continue
        for field in ("name", "status"):
            if not str(stage.get(field) or "").strip():
                findings.append(
                    Finding(name, "incomplete", f"{where}.{field} is empty")
                )
        status = str(stage.get("status") or "")
        if status and status not in _STAGE_STATUSES:
            findings.append(
                Finding(
                    name,
                    "schema",
                    f"{where}.status {status!r} is not one of "
                    f"{', '.join(_STAGE_STATUSES)}",
                )
            )
        commit = str(stage.get("commit") or "").strip()
        if commit and not _commit_is_in_history(commit):
            findings.append(
                Finding(
                    name,
                    "unverifiable-commit",
                    f"{where}.commit {commit} is not an ancestor of HEAD",
                )
            )
    return findings


def _audit_one(name: str, receipt: Any, stale: list[str]) -> list[Finding]:
    """Check a single receipt, appending to ``stale`` when it is out of date."""
    if not isinstance(receipt, dict):
        return [Finding(name, "schema", "receipt must be a mapping")]

    findings = _shape_problems(name, receipt)
    findings += _stages_problems(name, receipt.get("stages"))
    status = receipt.get("status")
    if status not in _STATUSES or status == "deferred":
        # A deferral is a decision, so it needs a reason and nothing else.
        return findings
    return findings + _recorded_problems(name, receipt, stale)


def format_report(ledger: dict[str, Any], stale: list[str]) -> str:
    """Render the human-facing summary of the ledger's state."""
    receipts = ledger.get("receipts", {})
    lines = ["### Operator-run verification protocols", ""]
    if repository_is_shallow():
        # Say so, loudly. A green from a checkout that could not perform the
        # ancestry check is not the same green as one that did, and a reader
        # who cannot tell them apart will trust the weaker one.
        lines += [
            "> This checkout is **shallow**, so the commit-ancestry check was "
            "not performed. Staleness is unknown here too. Run with full "
            "history (`fetch-depth: 0`) for the enforcing report.",
            "",
        ]
    lines.append("| Protocol | Status | Recorded at | Current |")
    lines.append("|---|---|---|---|")
    for name in sorted(receipts):
        receipt = receipts[name]
        commit = str(receipt.get("commit") or "")
        current = (
            "n/a"
            if receipt.get("status") == "deferred"
            else ("STALE" if name in stale else "yes")
        )
        lines.append(
            f"| `{name}` | {receipt.get('status')} | "
            f"{commit[:8] or '—'} | {current} |"
        )
    if stale:
        lines += [
            "",
            "Stale receipts vouch for a tree that has since moved. They do not "
            "fail the build -- re-run the protocol and re-record it when the "
            "change warrants:",
            "",
        ]
        for name in stale:
            moved = changed_since(
                str(receipts[name].get("commit")), list(receipts[name]["watched"])
            )
            shown = ", ".join(moved[:5]) + (" …" if len(moved) > 5 else "")
            lines.append(f"- `{name}`: {len(moved)} watched file(s) changed — {shown}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run the receipt gate or report on the ledger.

    Args:
        argv: Argument list; defaults to ``sys.argv[1:]``.

    Returns:
        0 when the ledger is sound, 1 when it carries findings.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="audit the ledger and print the report (default)",
    )
    parser.add_argument(
        "--ledger", type=Path, default=RECEIPTS_PATH, help="ledger location"
    )
    args = parser.parse_args(argv)

    ledger = load_receipts(args.ledger)
    findings, stale = audit(ledger)
    print(format_report(ledger, stale))
    if findings:
        print("", file=sys.stderr)
        print(
            f"verification receipts FAILED ({len(findings)} finding(s)):",
            file=sys.stderr,
        )
        for finding in findings:
            print(f"  {finding.located()}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
