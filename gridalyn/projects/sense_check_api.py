"""The surface a study writes its own objective sense checks against.

A sense check answers whether a study's generated values are plausible for its
stated objective -- a different question from schema validity (``validation.py``)
and from baseline drift (``regression.py``).

Those checks are study knowledge, so they live beside the study, not here.
Until 2026-08-14 the six shipped studies' checkers lived inside
``gridalyn/projects/sense_checks.py``: 424 lines, 53% of that module, teaching
the library that IEEE-33 has 37 branches and that the RL action space is
``{-0.12, 0.0, 0.12}``. Adding a study meant editing the library, and the
library carried facts about consumers it should not have known. This module is
the seam that ended that: the library supplies the vocabulary, each study
supplies its own checks and declares them in ``project.yaml``.

A study checker is a module-level function taking ``(project, checks)`` and
appending to ``checks`` through :func:`record_check`::

    from gridalyn.projects.sense_check_api import between, record_check, report_summary

    def check(project, checks) -> None:
        summary = report_summary(project, "outputs/reports/my_report.json")
        record_check(
            checks,
            "min_voltage_plausible",
            between(summary.get("min_voltage_pu"), 0.90, 1.05),
            summary.get("min_voltage_pu"),
            "0.90 - 1.05",
        )

and is declared as a project-relative ``<path>.py:<function>`` reference::

    spec:
      validation:
        senseChecker: scripts/sense_checks.py:check
        objectiveArtifacts:
          - outputs/reports/my_report.json
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from gridalyn.projects.models import StudyProject

#: The accumulator a checker appends its results to.
CheckList = list[dict[str, Any]]

#: Severity levels. Only ``"error"`` failures make a sense-check report invalid;
#: ``"warning"`` failures are reported and lower the score without failing it.
CHECK_SEVERITIES = ("error", "warning")


def read_json_report(project: StudyProject, relative: str) -> dict[str, Any]:
    """Read a JSON artifact from a project-relative path.

    Args:
        project: The study being checked.
        relative: Path relative to ``project.root``.

    Returns:
        The parsed JSON object.
    """
    return json.loads((project.root / relative).read_text(encoding="utf-8"))


def report_summary(project: StudyProject, relative: str) -> dict[str, Any]:
    """Read the ``summary`` block of a platform report.

    Args:
        project: The study being checked.
        relative: Path to the report, relative to ``project.root``.

    Returns:
        The report's ``summary`` mapping, or an empty dict when absent.
    """
    return read_json_report(project, relative).get("summary", {})


def read_csv(project: StudyProject, relative: str) -> pd.DataFrame:
    """Read a CSV artifact from a project-relative path.

    Args:
        project: The study being checked.
        relative: Path relative to ``project.root``.

    Returns:
        The parsed frame.
    """
    return pd.read_csv(project.root / relative)


def between(value: float | int | None, low: float, high: float) -> bool:
    """Report whether ``value`` is present and within an inclusive range.

    Args:
        value: The observed quantity, possibly missing.
        low: Inclusive lower bound.
        high: Inclusive upper bound.

    Returns:
        True when ``value`` is not ``None`` and ``low <= value <= high``. A
        missing value is False rather than an exception, so one absent metric
        fails its own check instead of aborting the whole sense-check run.
    """
    return value is not None and low <= float(value) <= high


def record_check(
    checks: CheckList,
    check_id: str,
    condition: bool,
    observed: Any,
    expected: Any,
    severity: str = "error",
) -> None:
    """Append one check result to a study's check list.

    Args:
        checks: The accumulator handed to the checker.
        check_id: Stable snake_case identifier, used as the reported message
            when none is derived.
        condition: Whether the check passed.
        observed: What the artifact actually contained.
        expected: What the objective implies it should have contained; free
            text such as ``"0.90 - 1.05"`` is fine and reads well in a report.
        severity: ``"error"`` (fails the report) or ``"warning"``.

    Raises:
        ValueError: If ``severity`` is not a known level. The message lists the
            valid set, because a typo would otherwise silently downgrade a
            failing check to something that fails nothing.
    """
    if severity not in CHECK_SEVERITIES:
        raise ValueError(
            f"unknown sense-check severity {severity!r} for check {check_id!r} "
            f"(known: {', '.join(CHECK_SEVERITIES)})"
        )
    from gridalyn.projects.sense_checks import _record

    _record(checks, check_id, condition, severity, observed, expected)


__all__ = [
    "CHECK_SEVERITIES",
    "CheckList",
    "between",
    "read_csv",
    "read_json_report",
    "record_check",
    "report_summary",
]
