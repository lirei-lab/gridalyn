"""Gate: a baseline may change, but not silently.

CLAUDE.md states the rule as cross-cutting and non-negotiable -- "a generator or
kernel change that moves a validated axis needs either a fix or a deliberate,
documented re-base -- never a silent baseline update". The word doing the work is
*silent*: changing a pin is legitimate, changing it without saying so is not.

What was already enforced, and what was not
-------------------------------------------
``tools/check_calibration_claims.py`` compares ``ev_hosting_flex``'s "Current
headline figures" table against the pins it cites, and ``test_calibration_claims``
runs it unconditionally, CI included. Measured 2026-09-10, that covers **33 of the
flagship's 94 pins**. Proved by mutation in the CI condition -- study outputs moved
out of the tree, the way a clean checkout sees it:

    a GATED pin moved 10%     ->  1 failed   (caught)
    an UNGATED pin moved 10%  ->  338 passed (not caught)

With outputs present both are caught, by the reproduce-and-pin tests. Those skip
in CI because study outputs are gitignored, so on a clean checkout the other 61
pins had nothing standing behind them. The seven other studies, 42 pins between
them, had nothing at all -- none of them even has a ``CALIBRATION.md`` to state a
rationale in.

What this gate does, and what it deliberately does not
------------------------------------------------------
Each study records the sha256 of its own ``results_baseline.json`` in
``baselines/REBASE_LOG.md``, newest entry last. This test recomputes it. Moving
any pin changes the digest and fails here, naming the study, both digests and the
remedy.

It does **not** verify that the new numbers are right -- that needs the study's
outputs, which is exactly what CI does not have. It verifies that somebody wrote
down that they changed and why. That is the half the rule actually forbids
leaving out, and it is the half a clean checkout can check.

A digest ledger is honest about its own weakness: an author can update the digest
without thinking. It cannot stop that, and pretending otherwise would be the
vacuous-gate shape this repo has shipped before. What it removes is the case
where nobody notices at all.
"""

from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PROJECTS = _REPO_ROOT / "projects"
_LOG_NAME = "REBASE_LOG.md"

#: ``sha256: <64 hex>`` on a line of its own, anywhere in an entry.
_DIGEST = re.compile(r"^\s*sha256:\s*([0-9a-f]{64})\s*$", re.MULTILINE)


def _studies_with_baselines() -> list[Path]:
    """Return every study directory carrying a pinned baseline."""
    return sorted(
        path.parent.parent
        for path in _PROJECTS.glob("*/baselines/results_baseline.json")
    )


def _digest(path: Path) -> str:
    """Return the sha256 of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


class BaselineRebaseIsDeclaredTest(unittest.TestCase):
    """Every pinned baseline's current bytes must be the ones last declared."""

    def test_every_study_with_a_baseline_has_a_rebase_log(self) -> None:
        """A study cannot opt out by simply not having the file."""
        missing = [
            study.name
            for study in _studies_with_baselines()
            if not (study / "baselines" / _LOG_NAME).is_file()
        ]
        self.assertEqual(
            missing,
            [],
            f"these studies pin a baseline with no {_LOG_NAME} beside it, so a "
            f"change to their pins would be unrecorded: {missing}. Create it with "
            "a dated entry and the current sha256 of results_baseline.json.",
        )

    def test_each_baseline_matches_the_digest_last_declared(self) -> None:
        """The whole point: moved pins that nobody wrote down fail here."""
        drifted: list[str] = []
        for study in _studies_with_baselines():
            log = study / "baselines" / _LOG_NAME
            if not log.is_file():
                continue  # reported by the test above
            declared = _DIGEST.findall(log.read_text(encoding="utf-8"))
            baseline = study / "baselines" / "results_baseline.json"
            if not declared:
                drifted.append(f"{study.name}: {_LOG_NAME} declares no sha256")
                continue
            actual = _digest(baseline)
            if declared[-1] != actual:
                drifted.append(
                    f"{study.name}: baseline is {actual[:12]}..., last declared "
                    f"{declared[-1][:12]}..."
                )
        self.assertEqual(
            drifted,
            [],
            "a pinned baseline changed without being declared:\n  "
            + "\n  ".join(drifted)
            + f"\nAppend a dated entry to the study's baselines/{_LOG_NAME} saying "
            "WHAT moved and WHY, with the new sha256. A re-base is allowed; an "
            "unexplained one is not.",
        )

    def test_the_digest_check_can_fail(self) -> None:
        """A gate that cannot fail proves nothing about the tree it guards."""
        with self.subTest("a matching digest passes"):
            self.assertTrue(_DIGEST.search("sha256: " + "a" * 64))
        with self.subTest("a truncated digest is not accepted"):
            self.assertIsNone(_DIGEST.search("sha256: " + "a" * 63))
        with self.subTest("the digest of different bytes differs"):
            one = hashlib.sha256(b'{"metrics": [1]}').hexdigest()
            two = hashlib.sha256(b'{"metrics": [2]}').hexdigest()
            self.assertNotEqual(one, two)


if __name__ == "__main__":
    unittest.main()
