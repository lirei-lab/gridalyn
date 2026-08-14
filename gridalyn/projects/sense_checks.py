"""Objective-level verification for Gridalyn study projects.

The mechanism lives here; the checks themselves live beside each study. A study
declares ``spec.validation.senseChecker`` and ``spec.validation.objectiveArtifacts``
in its ``project.yaml``, and this module discovers both. Authors write against
:mod:`gridalyn.projects.sense_check_api`.

That split is a repair. Until 2026-08-14 this module held the six shipped
studies' checkers -- 424 lines, 53% of the file -- plus two dicts keyed by
project name that had to stay in sync by hand. It meant the library knew that
IEEE-33 has 37 branches, and that adding a study to ``projects/`` required
editing ``gridalyn/``: the consumer could not be extended without modifying its
own dependency.
"""

from __future__ import annotations

import importlib.util
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

import pandas as pd

from gridalyn.foundation.platform.reports import ReportMetadata, write_report
from gridalyn.projects.loader import load_project
from gridalyn.projects.models import StudyProject

CheckList = list[dict[str, Any]]


def project_sense_check(path: Path | str, write: bool = True) -> dict[str, Any]:
    """Run objective-specific plausibility checks for a project.

    These checks complement project validation. Project validation answers
    whether required artifacts exist and reports follow the platform schema.
    Sense checks answer whether the generated values make sense for the demo's
    stated objective.

    The returned dict keeps the flat legacy shape (top-level ``valid``,
    ``score``, ``checks``, ...) that ``project_verify`` and the CLI read; the
    on-disk report is routed through the platform ``write_report`` helper and
    carries the governed envelope only (audit section 5.3).
    """

    project = load_project(_project_file(path))
    checks: CheckList = []
    _common_artifact_checks(project, checks)
    declared_checks = _declarative_sense_checks(project, checks)
    checker = _load_project_checker(project)
    # These are two independent facts about a run and are recorded
    # independently. The previous if/elif chain reported whichever it reached
    # first, so a project that both declared nothing AND was missing its
    # artifacts disclosed only one of the two -- and, because the lookup was
    # keyed by project name, artifacts declared by a study with no code checker
    # were never checked at all.
    missing = _missing_objective_artifacts(project)
    if missing:
        _record(
            checks,
            "missing_objective_artifact",
            False,
            "error",
            missing,
            "all objective artifacts exist",
            "Run the project workflow before objective-level sense checks.",
        )
    if checker is None and declared_checks == 0:
        _record(
            checks,
            "project_has_registered_sense_checks",
            False,
            "error",
            project.name,
            "spec.validation.senseChecker or spec.validation.senseChecks",
            "A study must declare either a sense-check module "
            "(spec.validation.senseChecker: <path>.py:<function>) or "
            "declarative rules (spec.validation.senseChecks); a project "
            "cannot pass sense checks vacuously.",
        )
    elif checker is not None and not missing:
        # The checker reads those artifacts, so running it with any of them
        # absent would replace a located 'missing_objective_artifact' with a
        # FileNotFoundError traceback.
        checker(project, checks)

    error_failures = [
        item for item in checks if item["severity"] == "error" and not item["passed"]
    ]
    passed_count = sum(1 for item in checks if item["passed"])
    score = passed_count / len(checks) if checks else 0.0
    summary: dict[str, Any] = {
        "checked_count": len(checks),
        "passed_count": passed_count,
        "failed_count": len(checks) - passed_count,
        "error_count": len(error_failures),
        "score": score,
    }
    validation: dict[str, Any] = {
        "valid": not error_failures,
        "errors": [item["id"] for item in error_failures],
        "warnings": [
            item["id"]
            for item in checks
            if item["severity"] == "warning" and not item["passed"]
        ],
    }
    payload = {
        "report_id": "project_sense_check_report",
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_domain": "project_verification",
        "project": project.name,
        "inputs": [],
        "artifacts": [],
        "summary": summary,
        "validation": validation,
        "valid": not error_failures,
        "checked_count": len(checks),
        "passed_count": passed_count,
        "failed_count": len(checks) - passed_count,
        "error_count": len(error_failures),
        "score": score,
        "checks": checks,
    }
    if write:
        out = project.root / "outputs" / "reports" / "project_sense_check_report.json"
        write_report(
            out,
            metadata=ReportMetadata(
                report_id="project_sense_check_report",
                source_domain="project_verification",
                project={"name": project.name},
            ),
            inputs=[],
            artifacts=[],
            summary=summary,
            validation=validation,
        )
    return payload


def _project_file(path: Path | str) -> Path:
    candidate = Path(path)
    if candidate.name == "project.yaml":
        return candidate
    return candidate / "project.yaml"


def _read_json(project: StudyProject, relative: str) -> dict[str, Any]:
    return json.loads((project.root / relative).read_text(encoding="utf-8"))


def _summary(project: StudyProject, relative: str) -> dict[str, Any]:
    return _read_json(project, relative).get("summary", {})


def _csv(project: StudyProject, relative: str) -> pd.DataFrame:
    return pd.read_csv(project.root / relative)


def _record(
    checks: CheckList,
    check_id: str,
    passed: bool,
    severity: str,
    observed: Any,
    expected: Any,
    message: str | None = None,
) -> None:
    checks.append(
        {
            "id": check_id,
            "severity": severity,
            "passed": bool(passed),
            "observed": _json_safe(observed),
            "expected": _json_safe(expected),
            "message": message or check_id.replace("_", " "),
        }
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return str(value)
    if hasattr(value, "item"):
        return value.item()
    return value


def _check(
    checks: CheckList,
    check_id: str,
    condition: bool,
    observed: Any,
    expected: Any,
    severity: str = "error",
) -> None:
    _record(checks, check_id, condition, severity, observed, expected)


def _between(value: float | int | None, low: float, high: float) -> bool:
    return value is not None and low <= float(value) <= high


def _common_artifact_checks(project: StudyProject, checks: CheckList) -> None:
    _check(
        checks,
        "project_manifest_exists",
        (project.root / "outputs/manifests/project_run_manifest.json").exists(),
        "outputs/manifests/project_run_manifest.json",
        "existing run manifest",
    )
    required = project.raw.get("spec", {}).get("validation", {})
    for index, relative in enumerate(required.get("requiredReports", []), start=1):
        _check(
            checks,
            f"required_report_{index}_exists",
            (project.base_dir / relative).exists(),
            relative,
            "existing report",
        )
    for index, relative in enumerate(required.get("requiredFigures", []), start=1):
        figure = project.base_dir / relative
        _check(
            checks,
            f"required_figure_{index}_exists",
            figure.exists() and figure.stat().st_size > 0,
            relative,
            "existing non-empty figure",
        )


def _declarative_sense_checks(project: StudyProject, checks: CheckList) -> int:
    declared = project.raw.get("spec", {}).get("validation", {}).get("senseChecks", [])
    if not isinstance(declared, list):
        _record(
            checks,
            "declared_sense_checks_shape",
            False,
            "error",
            type(declared).__name__,
            "list",
        )
        return 1

    for index, rule in enumerate(declared, start=1):
        _run_declarative_sense_check(project, checks, rule, index)
    return len(declared)


def _run_declarative_sense_check(
    project: StudyProject,
    checks: CheckList,
    rule: dict[str, Any],
    index: int,
) -> None:
    check_id = str(rule.get("id") or f"declared_sense_check_{index}")
    severity = str(rule.get("severity", "error"))
    report_path = rule.get("report")
    field = rule.get("field")
    if not report_path or not field:
        _record(
            checks,
            check_id,
            False,
            severity,
            {"report": report_path, "field": field},
            "rule with report and field",
            rule.get("message"),
        )
        return

    try:
        payload = json.loads(
            (project.base_dir / str(report_path)).read_text(encoding="utf-8")
        )
        observed = _resolve_field(payload, str(field))
    except Exception as exc:
        _record(
            checks,
            check_id,
            False,
            severity,
            str(exc),
            f"{report_path}:{field}",
            rule.get("message"),
        )
        return

    passed, expected = _evaluate_declarative_rule(observed, rule)
    _record(
        checks,
        check_id,
        passed,
        severity,
        observed,
        expected,
        rule.get("message"),
    )


def _resolve_field(payload: dict[str, Any], field: str) -> Any:
    value: Any = payload
    for part in field.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            raise KeyError(field)
    return value


def _evaluate_declarative_rule(observed: Any, rule: dict[str, Any]) -> tuple[bool, Any]:
    expectations = []
    if "equals" in rule:
        expected = rule["equals"]
        expectations.append((observed == expected, f"== {expected!r}"))
    numeric_ops = [
        ("min", lambda value, limit: value >= limit, ">="),
        ("max", lambda value, limit: value <= limit, "<="),
        ("gt", lambda value, limit: value > limit, ">"),
        ("gte", lambda value, limit: value >= limit, ">="),
        ("lt", lambda value, limit: value < limit, "<"),
        ("lte", lambda value, limit: value <= limit, "<="),
    ]
    for key, predicate, label in numeric_ops:
        if key in rule:
            limit = float(rule[key])
            try:
                observed_number = float(observed)
            except (TypeError, ValueError):
                expectations.append((False, f"{label} {limit}"))
            else:
                expectations.append(
                    (predicate(observed_number, limit), f"{label} {limit}")
                )
    if not expectations:
        return False, "one of equals, min, max, gt, gte, lt, lte"
    return all(item[0] for item in expectations), " and ".join(
        item[1] for item in expectations
    )


def _validation_spec(project: StudyProject) -> Mapping[str, Any]:
    spec = project.raw.get("spec", {}) if isinstance(project.raw, dict) else {}
    validation = spec.get("validation", {}) if isinstance(spec, dict) else {}
    return validation if isinstance(validation, Mapping) else {}


def _objective_artifacts(project: StudyProject) -> tuple[str, ...]:
    """Return the artifacts a study declares its objective must produce.

    Args:
        project: The loaded study.

    Returns:
        The declared project-relative paths, empty when the study declares
        none. This replaces a module-level dict keyed by project name, which
        had to be kept in sync by hand with a second dict of checkers: a study
        added to one and forgotten in the other silently checked nothing.

    Raises:
        ValueError: If ``spec.validation.objectiveArtifacts`` is present but is
            not a list of strings.
    """
    declared = _validation_spec(project).get("objectiveArtifacts", [])
    if not isinstance(declared, list) or not all(
        isinstance(item, str) for item in declared
    ):
        raise ValueError(
            f"{project.path}: spec.validation.objectiveArtifacts must be a list "
            f"of project-relative path strings, found {type(declared).__name__}"
        )
    return tuple(declared)


def _missing_objective_artifacts(project: StudyProject) -> list[str]:
    return [
        relative
        for relative in _objective_artifacts(project)
        if not (project.root / relative).exists()
    ]


def _load_project_checker(
    project: StudyProject,
) -> Callable[[StudyProject, CheckList], None] | None:
    """Load the sense checker a study declares, if it declares one.

    The library holds no table of study names. A study points at its own
    checker with ``spec.validation.senseChecker: <path>.py:<function>``,
    resolved relative to the project root, so adding a study requires no edit
    here. That direction matters: ``gridalyn`` is the library and ``projects``
    is its consumer, and a name table here made the library depend on facts
    about consumers it should not know.

    Args:
        project: The loaded study.

    Returns:
        The declared callable, or ``None`` when the study declares no checker.

    Raises:
        ValueError: If the reference is malformed, the module cannot be
            imported, or the named attribute is missing or not callable. Every
            message names the project file, the declared reference and the fix.
    """
    reference = _validation_spec(project).get("senseChecker")
    if reference is None:
        return None
    if not isinstance(reference, str) or ":" not in reference:
        raise ValueError(
            f"{project.path}: spec.validation.senseChecker must be "
            f"'<project-relative-module>.py:<function>', found {reference!r}"
        )
    relative, _, attribute = reference.rpartition(":")
    module_path = project.root / relative
    if not module_path.is_file():
        raise ValueError(
            f"{project.path}: spec.validation.senseChecker points at "
            f"{module_path}, which does not exist; create it or correct "
            f"the declared path {relative!r}"
        )
    spec = importlib.util.spec_from_file_location(
        f"_gridalyn_sense_checks_{project.name}", module_path
    )
    if spec is None or spec.loader is None:
        raise ValueError(
            f"{project.path}: spec.validation.senseChecker could not load "
            f"{module_path} as a Python module"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    checker = getattr(module, attribute, None)
    if not callable(checker):
        available = ", ".join(sorted(n for n in vars(module) if not n.startswith("_")))
        raise ValueError(
            f"{project.path}: spec.validation.senseChecker names "
            f"{attribute!r} in {relative}, which is not callable "
            f"(module defines: {available or 'nothing public'})"
        )
    return checker


__all__ = ["project_sense_check"]
