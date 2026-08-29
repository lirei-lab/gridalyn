"""The three ``gridalyn twin verify-*`` scripts, exercised rather than trusted.

Why this exists
---------------
``verify_digital_twin_ev_scenarios``, ``..._timeseries`` and ``..._powerflow``
back three user-facing CLI subcommands and existed with nothing checking them.
They appeared together in all three of a 2026-08-28 measurement pass -- no test
named any of them, each carried an ``E402`` its sibling script had already
silenced with a ``# noqa``, and each was over the complexity ceiling at 14, 15
and 13. Code whose entire job is checking, with nothing checking it.

The reason they were untestable was structural: every failure was a
``SystemExit`` raised inline, so the only observable outcome was the process
dying. Each now has a ``verify_*`` function that RETURNS
``{"valid", "error", "lines"}`` and a ``main`` that prints and exits -- the
shape ``verify_dashboard_consistency.py`` already used.

**The most important test here is the one where verification FAILS.** A
verifier that cannot be shown to reject a bad input is indistinguishable from
one that always passes, which is exactly the defect this set is guarding
against.

These tests skipif when the twin instance is absent: the committed twin is a
large gitignored artifact set, so CI has no copy. The skip reason names what is
missing, per ``test_skip_visibility.py``.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import pandas as pd
import pytest

from gridalyn.projects.workflows.scripts.verify_digital_twin_ev_powerflow import (
    verify_scenarios,
)
from gridalyn.projects.workflows.scripts.verify_digital_twin_ev_scenarios import (
    verify_scenario_overlays,
)
from gridalyn.projects.workflows.scripts.verify_digital_twin_ev_timeseries import (
    verify_ev_timeseries,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TWIN = _REPO_ROOT / "instances" / "default" / "digital_twin"
_BASE = _TWIN / "base"
_SCENARIOS = _TWIN / "scenarios"
_TIMESERIES = _TWIN / "timeseries"

_SKIP = (
    "digital-twin instance artifacts absent: build them with `gridalyn twin "
    "build` (they are gitignored, so CI has no copy)"
)
_HAVE_TWIN = (
    (_BASE / "buildings.parquet").is_file()
    and (_SCENARIOS / "ev_assignments.parquet").is_file()
    and (_TIMESERIES / "ev_load_summary.json").is_file()
)


class VerifierContractTests(unittest.TestCase):
    """Shape of the report, independent of whether a twin is present."""

    def test_every_verifier_returns_the_same_report_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp)
            reports = [
                _safely(
                    lambda: verify_scenario_overlays(base_dir=empty, scenario_dir=empty)
                ),
                _safely(
                    lambda: verify_ev_timeseries(
                        base_dir=empty, scenario_dir=empty, timeseries_dir=empty
                    )
                ),
                _safely(lambda: verify_scenarios(["S0"], empty, empty)),
            ]
        for report in reports:
            if report is None:
                # A missing FILE still raises; only failed CHECKS are returned.
                # That distinction is deliberate and is asserted below.
                continue
            self.assertEqual({"valid", "error", "lines"}, set(report))

    def test_a_missing_artifact_raises_rather_than_reporting_invalid(self) -> None:
        """An absent file is not a failed check.

        Reporting `valid: false` for a twin that was never built would conflate
        "this twin is wrong" with "there is no twin here", and the operator
        needs to tell those apart.
        """
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp)
            with self.assertRaises(OSError):  # FileNotFoundError subclasses it
                verify_scenario_overlays(base_dir=empty, scenario_dir=empty)


def _safely(call):
    try:
        return call()
    except (OSError, KeyError):  # FileNotFoundError is an OSError
        return None


@pytest.mark.skipif(not _HAVE_TWIN, reason=_SKIP)
class VerifiersAgainstTheCommittedTwinTests(unittest.TestCase):
    def test_timeseries_verification_passes(self) -> None:
        report = verify_ev_timeseries(
            base_dir=_BASE, scenario_dir=_SCENARIOS, timeseries_dir=_TIMESERIES
        )
        self.assertTrue(report["valid"], report["error"])
        self.assertTrue(report["lines"], "a passing run must still report per scenario")

    def test_powerflow_verification_passes(self) -> None:
        report = verify_scenarios(["S0", "S1"], _TIMESERIES, _BASE)
        self.assertTrue(report["valid"], report["error"])

    def test_scenario_overlay_verification_passes(self) -> None:
        """The committed twin's overlays match the seed their documents declare.

        This asserted only the report's SHAPE until 2026-08-29, because the
        committed twin failed: its assignment table had been regenerated on
        2026-05-18 with an explicit `--assignment-seed 123` that appears in no
        config, no default and no declaration, while every other artifact in
        the twin -- and the scenario documents themselves -- were built from
        the declared 1042. Regenerating from the declared seed restored
        coherence with the 2026-05-08 powerflow results, so this can now assert
        the outcome rather than accommodate the failure.
        """
        report = verify_scenario_overlays(base_dir=_BASE, scenario_dir=_SCENARIOS)
        self.assertTrue(report["valid"], report["error"])
        self.assertEqual(5, len(report["lines"]), report["lines"])


@pytest.mark.skipif(not _HAVE_TWIN, reason=_SKIP)
class VerifiersRejectBadInputTests(unittest.TestCase):
    """A verifier that cannot be shown to reject is not a verifier.

    Each case copies the committed twin into a temporary tree, corrupts exactly
    one property, and asserts the verifier names it.
    """

    def _twin_copy(self, tmp: str) -> tuple[Path, Path, Path]:
        root = Path(tmp)
        base, scen, ts = root / "base", root / "scenarios", root / "timeseries"
        for src, dst in ((_BASE, base), (_SCENARIOS, scen)):
            shutil.copytree(src, dst)
        ts.mkdir()
        for name in ("ev_load_summary.json",):
            shutil.copy(_TIMESERIES / name, ts / name)
        return base, scen, ts

    def test_a_wrong_ev_count_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base, scen, _ = self._twin_copy(tmp)
            frame = pd.read_parquet(scen / "ev_assignments.parquet")
            # Flip one building into having an EV in S1, so the count no longer
            # matches the declared 10%.
            target = frame.index[(frame["scenario_id"] == "S1") & (~frame["has_ev"])][0]
            frame.loc[target, "has_ev"] = True
            frame.to_parquet(scen / "ev_assignments.parquet")
            report = verify_scenario_overlays(base_dir=base, scenario_dir=scen)
        self.assertFalse(report["valid"])
        self.assertIn("S1", report["error"])
        self.assertIn("EVs", report["error"])

    def test_an_area_column_is_rejected(self) -> None:
        """Overlays must be independent of building area, by contract."""
        with tempfile.TemporaryDirectory() as tmp:
            base, scen, _ = self._twin_copy(tmp)
            frame = pd.read_parquet(scen / "ev_assignments.parquet")
            frame["area_m2"] = 1.0
            frame.to_parquet(scen / "ev_assignments.parquet")
            report = verify_scenario_overlays(base_dir=base, scenario_dir=scen)
        self.assertFalse(report["valid"])
        self.assertIn("area_m2", report["error"])

    def test_a_truncated_assignment_table_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base, scen, _ = self._twin_copy(tmp)
            frame = pd.read_parquet(scen / "ev_assignments.parquet")
            frame.iloc[:-1].to_parquet(scen / "ev_assignments.parquet")
            report = verify_scenario_overlays(base_dir=base, scenario_dir=scen)
        self.assertFalse(report["valid"])
        self.assertIn("assignment rows", report["error"])

    def test_a_failure_stops_at_the_first_problem(self) -> None:
        """Short-circuit order is behaviour, not an accident.

        Later checks index frames the earlier ones establish, so collecting all
        failures would replace a located message with a pandas traceback.
        """
        with tempfile.TemporaryDirectory() as tmp:
            base, scen, _ = self._twin_copy(tmp)
            frame = pd.read_parquet(scen / "ev_assignments.parquet")
            frame["area_m2"] = 1.0
            frame.iloc[:-1].to_parquet(scen / "ev_assignments.parquet")
            report = verify_scenario_overlays(base_dir=base, scenario_dir=scen)
        # Both defects are present; only the first is reported.
        self.assertIn("area_m2", report["error"])
        self.assertNotIn("assignment rows", report["error"])


if __name__ == "__main__":
    unittest.main()
