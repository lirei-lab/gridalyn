"""A study's stated headline figures must agree with its pinned baseline.

CLAUDE.md designates each CALIBRATION.md as the source of truth and tells
readers to consult it before quoting a metric. `ev_hosting_flex` carried a firm
P50 of 4 against a pinned 11 for over a month, because the file is written by
appending and a re-base moved the pins without revising the prose. Nothing
caught it: the doc-path checker validates paths, not numbers.

This gate reads only the "Current headline figures" table, where each row names
the pin it mirrors. Historical prose is deliberately not read -- superseded
numbers belong in a chronological record, and a gate that flagged them would be
noise nobody keeps.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

import check_calibration_claims as claims  # noqa: E402


class TestCalibrationClaims(unittest.TestCase):
    def test_at_least_one_study_is_gated(self) -> None:
        """A gate nothing opts into protects nothing."""
        self.assertTrue(
            claims.gated_studies(),
            "no CALIBRATION.md declares a 'Current headline figures' table; "
            "the gate would pass vacuously",
        )

    def test_every_gated_study_agrees_with_its_baseline(self) -> None:
        for study in claims.gated_studies():
            with self.subTest(study=study):
                failures = claims.check_study(study)
                self.assertEqual(
                    failures,
                    [],
                    f"{study}/CALIBRATION.md states figures its own baseline "
                    "refutes:\n  " + "\n  ".join(failures),
                )

    def test_the_flagship_is_among_them(self) -> None:
        """The study the defect was found in must stay covered."""
        self.assertIn("ev_hosting_flex", claims.gated_studies())

    def test_the_gate_catches_a_stale_figure(self) -> None:
        """Exercise the failure path, not only the passing one.

        A gate never seen to fail is not known to work. This reproduces the
        original defect shape -- a table figure that disagrees with its pin --
        without touching any tracked file.
        """
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            study = Path(tmp) / "projects" / "fake_study"
            (study / "baselines").mkdir(parents=True)
            (study / "baselines" / "results_baseline.json").write_text(
                json.dumps({"metrics": [{"id": "cred.firm_p50", "expected": 11.0}]}),
                encoding="utf-8",
            )
            (study / "CALIBRATION.md").write_text(
                "# Fake\n\n## Current headline figures\n\n"
                "| Figure | Current value | Baseline pin |\n"
                "|---|---|---|\n"
                "| Firm hosting, P50 | 4.0 EVs | `cred.firm_p50` |\n",
                encoding="utf-8",
            )
            original = claims.PROJECTS
            claims.PROJECTS = study.parent
            try:
                failures = claims.check_study("fake_study")
            finally:
                claims.PROJECTS = original

        self.assertEqual(len(failures), 1)
        self.assertIn("cred.firm_p50", failures[0])
        self.assertIn("4.0", failures[0])
        self.assertIn("11.0", failures[0])

    def test_a_row_naming_an_unknown_pin_fails(self) -> None:
        """A claim that mirrors nothing is as bad as one that mirrors wrongly."""
        import json
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            study = Path(tmp) / "projects" / "fake_study"
            (study / "baselines").mkdir(parents=True)
            (study / "baselines" / "results_baseline.json").write_text(
                json.dumps({"metrics": [{"id": "real.pin", "expected": 1.0}]}),
                encoding="utf-8",
            )
            (study / "CALIBRATION.md").write_text(
                "## Current headline figures\n\n"
                "| Figure | Current value | Baseline pin |\n"
                "|---|---|---|\n"
                "| Something | 1.0 | `no.such.pin` |\n",
                encoding="utf-8",
            )
            original = claims.PROJECTS
            claims.PROJECTS = study.parent
            try:
                failures = claims.check_study("fake_study")
            finally:
                claims.PROJECTS = original

        self.assertEqual(len(failures), 1)
        self.assertIn("no.such.pin", failures[0])

    def test_rounding_is_compared_at_the_displayed_precision(self) -> None:
        """The document may round for legibility, not to hide a moved pin."""
        parsed = claims.read_claims(
            REPO_ROOT / "projects" / "ev_hosting_flex" / "CALIBRATION.md"
        )
        by_pin = {refs[0]: (value, places) for _, refs, value, places in parsed}
        value, places = by_pin["insurance.expected_cost_flex_at_ref"]
        self.assertEqual(places, 2)
        # Against the pin itself, not a literal: a deliberate re-base of this
        # figure must not break the test that checks the document rounds
        # honestly (it did, at 480.06 -> 480.05 on 2026-09-04).
        baseline = json.loads(
            (
                REPO_ROOT
                / "projects"
                / "ev_hosting_flex"
                / "baselines"
                / "results_baseline.json"
            ).read_text()
        )
        expected = next(
            m["expected"]
            for m in baseline["metrics"]
            if m["id"] == "insurance.expected_cost_flex_at_ref"
        )
        self.assertEqual(value, round(expected, places))
        self.assertNotEqual(value, expected, "the document is expected to round")


class TestCalibrationKnobs(unittest.TestCase):
    """The knobs the document states must be the knobs the study declares.

    A second source of truth, and the same defect. The "Recommended values"
    review recommended lowering EV coincident power and capping the sweep;
    `10-03` adopted every recommendation; the table kept showing the
    pre-adoption numbers under a column headed "Current". A reader saw a model
    over-stated by ~71% on EV power and ~186% on session energy, with an
    "Action" column telling them to do work already done.
    """

    DOC = REPO_ROOT / "projects" / "ev_hosting_flex" / "CALIBRATION.md"

    def test_the_flagship_declares_a_knob_table(self) -> None:
        self.assertTrue(
            claims.read_knobs(self.DOC),
            "ev_hosting_flex must state its knobs where they can be gated",
        )

    def test_every_gated_study_agrees_with_its_declared_knobs(self) -> None:
        for study in claims.gated_studies():
            with self.subTest(study=study):
                self.assertEqual([], claims.check_study_knobs(study))

    def test_a_derived_knob_is_gated_as_the_product_of_its_factors(self) -> None:
        """Gating only the factors would leave the product free to drift."""
        rows = {row[0]: row for row in claims.read_knobs(self.DOC)}
        _, refs, value, places = rows["EV coincident draw per EV"]
        self.assertEqual(("evUnitKw", "diversityFactor"), refs)
        self.assertEqual(2.52, value)
        self.assertEqual(2, places)

    def test_the_knob_table_is_optional(self) -> None:
        """A study may adopt the pins gate without declaring knobs."""
        missing = REPO_ROOT / "tools" / "check_calibration_claims.py"
        self.assertEqual([], claims.read_knobs(missing))

    def test_the_gate_catches_a_knob_the_study_no_longer_uses(self) -> None:
        """The exact shape of the defect: a stale value under 'Current'."""
        import tempfile

        import yaml

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "fake_study"
            root.mkdir(parents=True)
            (root / "project.yaml").write_text(
                yaml.safe_dump(
                    {
                        "spec": {
                            "inputs": {
                                "studyConfig": {
                                    "evUnitKw": 7.2,
                                    "diversityFactor": 0.35,
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            (root / "CALIBRATION.md").write_text(
                "# Fake\n\n## Current knob values\n\n"
                "| Knob | Current value | Declared in |\n|---|---|---|\n"
                "| EV coincident draw | 4.32 kW | `evUnitKw` x `diversityFactor` |\n"
                "| Unknown | 1.0 | `notAKnob` |\n",
                encoding="utf-8",
            )
            original = claims.PROJECTS
            claims.PROJECTS = Path(tmp)
            try:
                failures = claims.check_study_knobs("fake_study")
            finally:
                claims.PROJECTS = original

        self.assertEqual(2, len(failures), failures)
        # The message must name both sides and the arithmetic, so the reader
        # can see which one moved without opening either file.
        self.assertIn("4.32", failures[0])
        self.assertIn("evUnitKw=7.2", failures[0])
        self.assertIn("2.52", failures[0])
        self.assertIn("notAKnob", failures[1])


class TestRetiredSectionsAreMarked(unittest.TestCase):
    """A section describing deleted code must say so.

    Not gateable by number: the CLPU section states four knobs that no longer
    exist in `config.py`, cites a determinism guard whose sha256 pins are gone,
    and points at `tests/test_ev_hosting_flex_stochastic.py`, a file that does
    not exist. Nothing numeric is wrong -- the whole section is.
    """

    DOC = REPO_ROOT / "projects" / "ev_hosting_flex" / "CALIBRATION.md"

    def test_the_clpu_section_is_marked_retired(self) -> None:
        text = self.DOC.read_text(encoding="utf-8")
        heading = "## Cold-load pickup (CLPU) base uplift"
        self.assertIn(heading, text)
        after = text.split(heading, 1)[1]
        banner = after.split("\n##", 1)[0][:1200]
        self.assertIn("RETIRED", banner)
        self.assertIn("RETIRE-02", banner)

    def test_the_symbols_it_documents_are_really_gone(self) -> None:
        """Pins the measurement, so a revival makes the banner wrong loudly.

        Comment lines are stripped before the check: `config.py` carries the
        deletion tombstone, which names `clpu_factor` precisely because it is
        gone. Matching that would make the guard fire on the evidence for its
        own claim.
        """
        scripts = REPO_ROOT / "projects" / "ev_hosting_flex" / "scripts"
        live = []
        for path in scripts.glob("*.py"):
            code = "\n".join(
                line
                for line in path.read_text(encoding="utf-8").splitlines()
                if not line.lstrip().startswith("#")
            )
            if "clpu_factor" in code:
                live.append(path.name)
        self.assertEqual([], live, "clpu_factor is back; unretire the section")
        self.assertFalse(
            (REPO_ROOT / "tests" / "test_ev_hosting_flex_stochastic.py").exists(),
            "the CLPU determinism guard is back; unretire the section",
        )

    def test_the_adopted_recommendation_is_recorded_as_adopted(self) -> None:
        """It recommended; the study adopted; the table must not still ask."""
        text = self.DOC.read_text(encoding="utf-8")
        self.assertIn("## Recommended values", text)
        section = text.split("## Recommended values", 1)[1].split("\n##", 1)[0]
        self.assertIn("ADOPTED", section)
        self.assertIn("Became", section)
        # The pre-adoption numbers stay, as the record of what was found.
        self.assertIn("4.32 kW", section)
        # But they must no longer sit under a column claiming to be current.
        self.assertNotIn("| Knob | Current | Defensible | Action |", section)


if __name__ == "__main__":
    unittest.main()
