"""The surface a study author writes its own sense checks against.

Why this exists
---------------
``gridalyn/projects/sense_check_api.py`` had no test naming it. It is the
*authoring* surface -- its own docstring says study checkers are written
against it -- and it was the one contract in the platform with nothing under
it. 14 of 162 SDK modules had no test mention, which is good coverage overall;
this is the one where the absence bites, because a sense check fails OPEN. A
checker that quietly stops checking still produces a report with a score, and
a report with a score reads as verification.

That failure mode was real, not hypothetical. Measured 2026-08-28: a study
declaring a ``senseChecker`` whose function recorded nothing produced
``valid: True`` with ``score: 1.00`` -- a perfect report from a study that
checked nothing, more convincing than one that actually ran.
``project_has_registered_sense_checks`` only fires when NO checker is declared,
so declaring one and not using it was the gap. ``project_sense_check`` now
records ``project_checker_recorded_no_checks`` as an error, and
:class:`VacuousCheckerTests` pins that.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

import pandas as pd

from gridalyn.projects.loader import load_project
from gridalyn.projects.sense_check_api import (
    CHECK_SEVERITIES,
    between,
    read_csv,
    read_json_report,
    record_check,
    report_summary,
)
from gridalyn.projects.sense_checks import project_sense_check

_PROBLEM = """\
  problem:
    type: powerflow_validation
    dataset: t
    environment: e
    objective: o
    model:
      type: simulation_model
      name: pandapower
    scenarios:
      - id: baseline
        role: r
        description: d
"""

_REPORT: dict[str, Any] = {
    "report_id": "r",
    "schema_version": "1.0",
    "created_at": "2026-01-01T00:00:00+00:00",
    "source_domain": "t",
    "inputs": {},
    "artifacts": [],
    "summary": {"min_voltage_pu": 0.95, "converged": True},
    "validation": {"valid": True},
}

_API_IMPORT = (
    "from gridalyn.projects.sense_check_api import "
    "between, record_check, report_summary\n\n"
)


def _write_project(
    root: Path, checker_body: str, *, declare_checker: bool = True
) -> Path:
    """Lay out the smallest project `project_sense_check` will accept."""
    (root / "scripts").mkdir()
    (root / "outputs" / "reports").mkdir(parents=True)
    (root / "outputs" / "manifests").mkdir(parents=True)
    (root / "outputs" / "data").mkdir(parents=True)
    (root / "outputs" / "manifests" / "project_run_manifest.json").write_text(
        json.dumps({"status": "completed"}), encoding="utf-8"
    )
    (root / "outputs" / "reports" / "r.json").write_text(
        json.dumps(_REPORT), encoding="utf-8"
    )
    (root / "outputs" / "data" / "rows.csv").write_text(
        "bus_id,vm_pu\n0,1.00\n1,0.95\n", encoding="utf-8"
    )
    (root / "scripts" / "sense_checks.py").write_text(checker_body, encoding="utf-8")
    (root / "workflow.yaml").write_text(
        "apiVersion: gridalyn/v1\nkind: Workflow\nmetadata:\n  name: t\n"
        "spec:\n  stages: []\n",
        encoding="utf-8",
    )
    declared = (
        "    senseChecker: scripts/sense_checks.py:check\n" if declare_checker else ""
    )
    (root / "project.yaml").write_text(
        "apiVersion: gridalyn/v1\nkind: StudyProject\n"
        "metadata:\n  name: t\n  version: 0.1.0\nspec:\n"
        + _PROBLEM
        + "  workflow:\n    file: workflow.yaml\n  validation:\n"
        + declared
        + "    objectiveArtifacts:\n      - outputs/reports/r.json\n",
        encoding="utf-8",
    )
    return root


class BetweenTests(unittest.TestCase):
    def test_inclusive_at_both_bounds(self) -> None:
        self.assertTrue(between(0.90, 0.90, 1.05))
        self.assertTrue(between(1.05, 0.90, 1.05))

    def test_outside_the_range_is_false(self) -> None:
        self.assertFalse(between(0.89, 0.90, 1.05))
        self.assertFalse(between(1.06, 0.90, 1.05))

    def test_a_missing_value_fails_its_own_check_rather_than_raising(self) -> None:
        """One absent metric must not abort the whole sense-check run."""
        self.assertFalse(between(None, 0.90, 1.05))

    def test_a_numeric_string_is_accepted(self) -> None:
        # `float(value)` is the documented coercion; a summary read from JSON
        # can legitimately carry a stringified number.
        self.assertTrue(between("0.95", 0.90, 1.05))  # type: ignore[arg-type]


class RecordCheckTests(unittest.TestCase):
    def test_a_recorded_check_carries_the_reported_shape(self) -> None:
        checks: list[dict[str, Any]] = []
        record_check(checks, "min_voltage_plausible", True, 0.95, "0.90 - 1.05")
        self.assertEqual(1, len(checks))
        entry = checks[0]
        self.assertEqual("min_voltage_plausible", entry["id"])
        self.assertEqual("error", entry["severity"])
        self.assertIs(True, entry["passed"])
        self.assertEqual(0.95, entry["observed"])
        self.assertEqual("0.90 - 1.05", entry["expected"])
        self.assertEqual("min voltage plausible", entry["message"])

    def test_an_unknown_severity_is_rejected_by_name(self) -> None:
        """A typo must not silently downgrade a failing check to nothing.

        `severity="eror"` would otherwise be recorded verbatim, and the
        error-failure filter matches `"error"` exactly, so the check would fail
        and the report would still be valid.
        """
        checks: list[dict[str, Any]] = []
        with self.assertRaises(ValueError) as caught:
            record_check(checks, "v", False, 1, 2, severity="eror")
        message = str(caught.exception)
        self.assertIn("eror", message)
        self.assertIn("v", message)
        for level in CHECK_SEVERITIES:
            self.assertIn(level, message)
        self.assertEqual([], checks, "a rejected severity must record nothing")

    def test_both_declared_severities_are_accepted(self) -> None:
        checks: list[dict[str, Any]] = []
        for level in CHECK_SEVERITIES:
            record_check(checks, f"c_{level}", True, 1, 1, severity=level)
        self.assertEqual(list(CHECK_SEVERITIES), [c["severity"] for c in checks])

    def test_a_non_json_value_is_made_safe_for_the_report(self) -> None:
        """Observed values reach a JSON artifact and must survive the trip."""
        checks: list[dict[str, Any]] = []
        record_check(checks, "c", True, pd.Series([1, 2]).sum(), 3)
        json.dumps(checks)  # must not raise


class ReaderTests(unittest.TestCase):
    def test_readers_resolve_paths_relative_to_the_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp), "def check(project, checks):\n    pass\n")
            project = load_project(root / "project.yaml")
            self.assertEqual(
                "r", read_json_report(project, "outputs/reports/r.json")["report_id"]
            )
            self.assertEqual(
                0.95,
                report_summary(project, "outputs/reports/r.json")["min_voltage_pu"],
            )
            frame = read_csv(project, "outputs/data/rows.csv")
            self.assertEqual([0, 1], list(frame["bus_id"]))

    def test_report_summary_of_a_report_without_one_is_empty_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp), "def check(project, checks):\n    pass\n")
            (root / "outputs" / "reports" / "bare.json").write_text(
                json.dumps({"report_id": "bare"}), encoding="utf-8"
            )
            project = load_project(root / "project.yaml")
            self.assertEqual({}, report_summary(project, "outputs/reports/bare.json"))


class VacuousCheckerTests(unittest.TestCase):
    """A study must not pass by declaring a checker it does not use."""

    def _run(self, body: str, *, declare_checker: bool = True) -> dict[str, Any]:
        with tempfile.TemporaryDirectory() as tmp:
            root = _write_project(Path(tmp), body, declare_checker=declare_checker)
            return project_sense_check(root, write=False)

    def test_a_checker_that_records_nothing_fails(self) -> None:
        result = self._run("def check(project, checks):\n    pass\n")
        self.assertFalse(
            result["valid"],
            "a checker recording nothing produced a passing report",
        )
        self.assertIn(
            "project_checker_recorded_no_checks",
            [check["id"] for check in result["checks"]],
        )

    def test_a_checker_that_records_a_passing_check_passes(self) -> None:
        result = self._run(
            _API_IMPORT + "def check(project, checks):\n"
            "    s = report_summary(project, 'outputs/reports/r.json')\n"
            "    record_check(checks, 'v_ok',"
            " between(s.get('min_voltage_pu'), 0.9, 1.05),"
            " s.get('min_voltage_pu'), '0.90 - 1.05')\n"
        )
        self.assertTrue(result["valid"], result["checks"])
        self.assertEqual(1.0, result["score"])

    def test_a_failing_error_check_invalidates_the_report(self) -> None:
        result = self._run(
            _API_IMPORT + "def check(project, checks):\n"
            "    record_check(checks, 'v_ok', False, 0.95, '1.50 - 2.00')\n"
        )
        self.assertFalse(result["valid"])
        self.assertIn("v_ok", result["validation"]["errors"])

    def test_a_failing_warning_lowers_the_score_without_invalidating(self) -> None:
        result = self._run(
            _API_IMPORT + "def check(project, checks):\n"
            "    record_check(checks, 'w', False, 1, 2, severity='warning')\n"
        )
        self.assertTrue(result["valid"], "a warning must not fail the report")
        self.assertLess(result["score"], 1.0, "a warning must still cost score")
        self.assertIn("w", result["validation"]["warnings"])

    def test_declaring_no_checker_at_all_still_fails(self) -> None:
        """The pre-existing gate must keep working alongside the new one."""
        result = self._run("", declare_checker=False)
        self.assertFalse(result["valid"])
        self.assertIn(
            "project_has_registered_sense_checks",
            [check["id"] for check in result["checks"]],
        )


if __name__ == "__main__":
    unittest.main()
