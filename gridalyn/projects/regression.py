"""Regression-baseline checks for Gridalyn projects."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


DEFAULT_BASELINE = "baselines/results_baseline.json"
DEFAULT_REPORT = "outputs/reports/regression_report.json"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def resolve_json_path(payload: Any, path: list[Any]) -> Any:
    current = payload
    for segment in path:
        current = current[segment]
    return current


def compare_regression_metric(
    *,
    project_root: Path,
    metric: dict[str, Any],
    default_tolerance: float,
) -> dict[str, Any]:
    """Compare one JSON metric from a project output against a baseline value."""
    source = project_root / metric["source"]
    record = {
        "id": metric["id"],
        "source": metric["source"],
        "json_path": metric["json_path"],
        "expected": metric["expected"],
    }
    if not source.exists():
        return {
            **record,
            "valid": False,
            "error": f"missing source: {metric['source']}",
        }

    try:
        actual = resolve_json_path(load_json(source), metric["json_path"])
    except Exception as exc:
        return {
            **record,
            "valid": False,
            "error": f"cannot resolve json_path: {exc}",
        }

    tolerance = float(metric.get("tolerance", default_tolerance))
    expected = metric["expected"]
    record["actual"] = actual
    record["tolerance"] = tolerance
    if isinstance(expected, bool):
        valid = actual is expected
    elif isinstance(expected, int | float) and isinstance(actual, int | float):
        valid = abs(float(actual) - float(expected)) <= tolerance
    else:
        valid = actual == expected
    record["valid"] = bool(valid)
    if not valid:
        record["error"] = f"expected {expected!r}, got {actual!r}"
    return record


def build_regression_report(
    *,
    project_root: Path,
    baseline_path: Path,
) -> dict[str, Any]:
    """Build a regression report from a JSON baseline contract."""
    baseline = load_json(baseline_path)
    default_tolerance = float(
        baseline.get("metric_tolerance", {}).get("absolute", 1e-6)
    )
    checks = [
        compare_regression_metric(
            project_root=project_root,
            metric=metric,
            default_tolerance=default_tolerance,
        )
        for metric in baseline.get("metrics", [])
    ]
    errors = [check["error"] for check in checks if not check["valid"]]
    return {
        "report_id": f"{baseline.get('project', project_root.name)}_regression",
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project": baseline.get("project", project_root.name),
        "baseline": str(baseline_path.relative_to(project_root)),
        "checked_count": len(checks),
        "valid_count": sum(1 for check in checks if check["valid"]),
        "valid": not errors,
        "errors": errors,
        "checks": checks,
    }


def write_regression_report(report: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return path


def run_project_regression(
    *,
    project_root: Path,
    baseline: str = DEFAULT_BASELINE,
    report: str = DEFAULT_REPORT,
) -> dict[str, Any]:
    """Run a project regression baseline and write the regression report."""
    project_root = project_root.resolve()
    baseline_path = (project_root / baseline).resolve()
    report_path = (project_root / report).resolve()
    regression_report = build_regression_report(
        project_root=project_root,
        baseline_path=baseline_path,
    )
    write_regression_report(regression_report, report_path)
    return regression_report


__all__ = [
    "DEFAULT_BASELINE",
    "DEFAULT_REPORT",
    "build_regression_report",
    "compare_regression_metric",
    "load_json",
    "resolve_json_path",
    "run_project_regression",
    "write_regression_report",
]
