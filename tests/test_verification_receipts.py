"""Gate for the operator-run verification receipts.

Some protocols in this repository are real, expensive and impossible to run
on a hosted runner -- the multi-hour flagship regeneration and its
shape-covering subset, the full documented-instruction sweep, the
subprocess-coverage measurement, the R7 twin-consumer identity capture over
the gitignored base, and the at-scale measured-ingest proof over the
gitignored HQ dataset (``REQUIRED_PROTOCOLS`` in
``tools/verification_receipt.py`` is the authoritative list). Before
``docs/development/verification-receipts.json`` existed they were tracked in
prose: a sentence claiming an operator had run something, with nothing tying
the claim to a tree.

What this gate buys, and what it does not
-----------------------------------------
It buys three things prose cannot give: every required protocol is declared,
each recorded receipt is complete rather than a bare "ok", and the commit a
receipt names really exists in this history and leads to HEAD. That last check
is the one with teeth -- it is what stops a receipt vouching for a tree nobody
can inspect, and it caught a fabricated SHA on the day it was written.

It does **not** buy proof that the protocol ran. A receipt asserts; a test
proves. This gate is therefore used only where the alternative is no
verification at all, and never to replace a job CI could run itself -- on
2026-08-06 a local suite passed while CI caught a real failure the local tree
could not see, which is precisely the failure mode a receipt cannot detect.

Staleness is reported, not enforced, for the reason the mypy ratchet reports
rather than demanding zero: a gate that requires a six-hour run before every
merge is a gate somebody switches off.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
import unittest
import unittest.mock
from pathlib import Path
from types import ModuleType

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TOOL_PATH = _REPO_ROOT / "tools" / "verification_receipt.py"


def _load_tool() -> ModuleType:
    """Import ``tools/verification_receipt.py`` without touching ``sys.path``."""
    spec = importlib.util.spec_from_file_location("verification_receipt", _TOOL_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - unreachable
        raise ImportError(f"cannot load {_TOOL_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tool = _load_tool()


class VerificationReceiptTests(unittest.TestCase):
    """The ledger is sound, and each of its rules has been watched failing."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.ledger = tool.load_receipts()

    def _require_full_history(self) -> None:
        """Skip when the checkout cannot answer ancestry questions.

        The rules below are about commits other than HEAD, so a depth-1 clone
        cannot exercise them either way. The CI job that enforces them sets
        `fetch-depth: 0`; everywhere else this announces itself rather than
        failing for a reason the change did not cause.
        """
        if tool.repository_is_shallow():
            self.skipTest(
                "shallow checkout: this rule reasons about commits other than "
                "HEAD, which a depth-1 clone does not carry. CI enforces it "
                "with fetch-depth: 0."
            )

    def test_the_ledger_is_sound(self) -> None:
        findings, _stale = tool.audit(self.ledger)
        self.assertEqual(
            [],
            [f.located() for f in findings],
            "the verification receipt ledger has findings; run "
            "'python tools/verification_receipt.py --check' for the report",
        )

    def test_every_required_protocol_is_declared(self) -> None:
        """A protocol cannot be claimed in prose and forgotten here."""
        self.assertEqual(
            sorted(tool.REQUIRED_PROTOCOLS),
            sorted(self.ledger["receipts"]),
        )

    def test_recorded_receipts_name_a_commit_in_this_history(self) -> None:
        """The anti-forgery rule, asserted directly rather than via the audit."""
        if tool.repository_is_shallow():
            self.skipTest(
                "shallow checkout: only the tip commit is present, so ancestry "
                "cannot be decided for any receipt. The CI job that enforces "
                "this rule sets fetch-depth: 0 for exactly this reason."
            )
        for name, receipt in sorted(self.ledger["receipts"].items()):
            if receipt.get("status") != "recorded":
                continue
            with self.subTest(protocol=name):
                self.assertTrue(
                    tool._commit_is_in_history(receipt["commit"]),
                    f"{name} vouches for {receipt['commit']}, which is not an "
                    "ancestor of HEAD",
                )

    def test_a_shallow_checkout_does_not_accuse_a_receipt_of_forgery(self) -> None:
        """Absence of evidence is not evidence of absence.

        A depth-1 clone -- what ``actions/checkout`` produces by default --
        cannot see any commit but its own tip. The first CI run of this gate
        read that blindness as four fabricated receipts and turned red on
        legitimate ones. The audit must now stay silent about ancestry there,
        and the report must say why, so a green from a shallow checkout is not
        mistaken for a green from a checked one.
        """
        with unittest.mock.patch.object(
            tool, "repository_is_shallow", return_value=True
        ):
            mutant = copy.deepcopy(self.ledger)
            mutant["receipts"]["docs-instruction-sweep"]["commit"] = "0" * 40
            findings, stale = tool.audit(mutant)

            self.assertEqual(
                [], [f.located() for f in findings], "shallow must not accuse"
            )
            self.assertEqual([], stale, "shallow cannot judge staleness either")
            self.assertIn("**shallow**", tool.format_report(mutant, stale))

    def test_a_deferral_must_give_its_reason(self) -> None:
        """A deferral is a decision; an empty one is an omission wearing a label."""
        for name, receipt in sorted(self.ledger["receipts"].items()):
            if receipt.get("status") != "deferred":
                continue
            with self.subTest(protocol=name):
                self.assertTrue(str(receipt.get("rationale") or "").strip())

    # -- mutations: each rule watched red -------------------------------------

    def test_a_fabricated_commit_turns_the_gate_red(self) -> None:
        """Mutation: the check that gives receipts their teeth.

        Watched green first, so the red is attributable to the mutation. The
        SHA below is well-formed and absent from every git history, which is
        exactly the shape a plausible-looking invented receipt takes -- one was
        written by accident on the day this gate landed, and this is what
        caught it.
        """
        self._require_full_history()
        mutant = copy.deepcopy(self.ledger)
        self.assertEqual([], tool.audit(mutant)[0])

        mutant["receipts"]["docs-instruction-sweep"]["commit"] = "0" * 40
        findings = tool.audit(mutant)[0]
        self.assertEqual(
            ["unverifiable-commit"],
            [f.kind for f in findings],
            findings,
        )

    def test_an_incomplete_receipt_turns_the_gate_red(self) -> None:
        """Mutation: a receipt that claims a run must say what came out."""
        mutant = copy.deepcopy(self.ledger)
        self.assertEqual([], tool.audit(mutant)[0])

        mutant["receipts"]["subprocess-coverage"]["result"] = ""
        findings = tool.audit(mutant)[0]
        self.assertEqual(["incomplete"], [f.kind for f in findings], findings)

    def test_a_dropped_protocol_turns_the_gate_red(self) -> None:
        """Mutation: an operator-only claim cannot quietly leave the ledger."""
        mutant = copy.deepcopy(self.ledger)
        self.assertEqual([], tool.audit(mutant)[0])

        del mutant["receipts"]["flagship-reproduce"]
        findings = tool.audit(mutant)[0]
        self.assertEqual(["undeclared"], [f.kind for f in findings], findings)

    def test_staleness_is_reported_and_never_fatal(self) -> None:
        """A moved tree makes a receipt stale, not the build red.

        Asserted in both directions so the distinction cannot erode: a receipt
        pinned at the repository's first commit is stale by construction, and
        the audit still returns no findings for it.
        """
        self._require_full_history()
        first_commit = subprocess.run(
            ["git", "rev-list", "--max-parents=0", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()[0]

        mutant = copy.deepcopy(self.ledger)
        mutant["receipts"]["docs-instruction-sweep"]["commit"] = first_commit
        findings, stale = tool.audit(mutant)

        self.assertEqual([], [f.located() for f in findings])
        self.assertIn("docs-instruction-sweep", stale)

    def test_the_cli_reports_and_exits_zero_on_a_sound_ledger(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(_TOOL_PATH), "--check"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("Operator-run verification protocols", completed.stdout)

    def test_the_ledger_is_valid_json_with_the_declared_schema(self) -> None:
        raw = json.loads(tool.RECEIPTS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(tool.SCHEMA_VERSION, raw["schema_version"])
        self.assertTrue(str(raw.get("note") or "").strip())

    # -- per-stage records (optional, validated when present) -----------------

    def test_valid_per_stage_records_pass_the_gate(self) -> None:
        """Mutation: well-formed stages on a recorded receipt change nothing."""
        self._require_full_history()
        mutant = copy.deepcopy(self.ledger)
        self.assertEqual([], tool.audit(mutant)[0])

        mutant["receipts"]["docs-instruction-sweep"]["stages"] = [
            {"name": "getting-started", "status": "ok", "commit": "ffcf4a7b"},
            {"name": "platform", "status": "ok"},
        ]
        self.assertEqual([], [f.located() for f in tool.audit(mutant)[0]])

    def test_a_stage_missing_name_or_status_turns_the_gate_red(self) -> None:
        """Mutation: a bare 'ok' stage is the per-stage form of a bare 'ok'."""
        mutant = copy.deepcopy(self.ledger)
        self.assertEqual([], tool.audit(mutant)[0])

        mutant["receipts"]["docs-instruction-sweep"]["stages"] = [
            {"name": "getting-started", "status": ""}
        ]
        findings = tool.audit(mutant)[0]
        self.assertEqual(["incomplete"], [f.kind for f in findings], findings)

    def test_a_stage_naming_a_fabricated_commit_turns_the_gate_red(self) -> None:
        """Mutation: a stage cannot vouch for a tree that never existed."""
        mutant = copy.deepcopy(self.ledger)
        self.assertEqual([], tool.audit(mutant)[0])

        mutant["receipts"]["docs-instruction-sweep"]["stages"] = [
            {"name": "getting-started", "status": "ok", "commit": "0" * 40}
        ]
        findings = tool.audit(mutant)[0]
        self.assertEqual(["unverifiable-commit"], [f.kind for f in findings])

    def test_stages_not_a_list_turns_the_gate_red(self) -> None:
        """Mutation: 'stages' must be a list of stage records."""
        mutant = copy.deepcopy(self.ledger)
        self.assertEqual([], tool.audit(mutant)[0])

        mutant["receipts"]["docs-instruction-sweep"]["stages"] = "not-a-list"
        findings = tool.audit(mutant)[0]
        self.assertEqual(["schema"], [f.kind for f in findings], findings)

    def test_a_non_dict_stage_element_turns_the_gate_red(self) -> None:
        """Mutation: each stage element must be a mapping."""
        mutant = copy.deepcopy(self.ledger)
        self.assertEqual([], tool.audit(mutant)[0])

        mutant["receipts"]["docs-instruction-sweep"]["stages"] = ["oops"]
        findings = tool.audit(mutant)[0]
        self.assertEqual(["schema"], [f.kind for f in findings], findings)

    def test_a_stage_with_invalid_status_turns_the_gate_red(self) -> None:
        """Mutation: a stage status must be ok/skipped/failed, not arbitrary."""
        mutant = copy.deepcopy(self.ledger)
        self.assertEqual([], tool.audit(mutant)[0])

        mutant["receipts"]["docs-instruction-sweep"]["stages"] = [
            {"name": "getting-started", "status": "banana"}
        ]
        findings = tool.audit(mutant)[0]
        self.assertEqual(["schema"], [f.kind for f in findings], findings)

    def test_the_cli_reports_findings_and_exits_one(self) -> None:
        """A bad ledger fails the CLI with the finding on stderr."""
        self._require_full_history()
        import tempfile

        bad = copy.deepcopy(self.ledger)
        bad["receipts"]["flagship-reproduce"]["commit"] = "0" * 40
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(bad, handle)
            bad_path = Path(handle.name)
        try:
            completed = subprocess.run(
                [sys.executable, str(_TOOL_PATH), "--check", "--ledger", str(bad_path)],
                cwd=_REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
        finally:
            bad_path.unlink(missing_ok=True)
        self.assertEqual(1, completed.returncode)
        self.assertIn("unverifiable-commit", completed.stderr)


if __name__ == "__main__":
    unittest.main()
