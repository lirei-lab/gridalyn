"""Verify EV capacity limitation outputs against a lightweight metric baseline."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
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


def compare_metric(
    *,
    project_root: Path,
    metric: dict[str, Any],
    default_tolerance: float,
) -> dict[str, Any]:
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
    baseline = load_json(baseline_path)
    default_tolerance = float(
        baseline.get("metric_tolerance", {}).get("absolute", 1e-6)
    )
    checks = [
        compare_metric(
            project_root=project_root,
            metric=metric,
            default_tolerance=default_tolerance,
        )
        for metric in baseline.get("metrics", [])
    ]
    errors = [check["error"] for check in checks if not check["valid"]]
    return {
        "report_id": "flexibility_cls_regression",
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=DEFAULT_PROJECT_ROOT)
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument("--report", default=DEFAULT_REPORT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root = args.project_root.resolve()
    baseline_path = (project_root / args.baseline).resolve()
    report_path = (project_root / args.report).resolve()
    report = build_regression_report(
        project_root=project_root,
        baseline_path=baseline_path,
    )
    write_regression_report(report, report_path)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
