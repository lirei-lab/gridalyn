"""Public report helpers and JSON report contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0"
REQUIRED_REPORT_FIELDS = (
    "report_id",
    "schema_version",
    "created_at",
    "source_domain",
    "inputs",
    "artifacts",
    "summary",
    "validation",
)


@dataclass(frozen=True)
class ReportMetadata:
    report_id: str
    source_domain: str
    schema_version: str = SCHEMA_VERSION
    project: dict[str, Any] = field(default_factory=dict)
    model_version_id: str | None = None
    study_run_id: str | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _relative(path: Path, root: Path | None) -> str:
    if root is None:
        return path.as_posix()
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def file_reference(path: Path | str, root: Path | str | None = None) -> dict[str, Any]:
    """Return a small provenance record for a file."""
    file_path = Path(path)
    root_path = Path(root) if root is not None else None
    item: dict[str, Any] = {"path": _relative(file_path, root_path)}
    if file_path.exists() and file_path.is_file():
        data = file_path.read_bytes()
        item["bytes"] = len(data)
        item["sha256"] = hashlib.sha256(data).hexdigest()
    else:
        item["exists"] = False
    return item


def build_report(
    *,
    metadata: ReportMetadata,
    inputs: list[dict[str, Any]] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    summary: dict[str, Any] | None = None,
    validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a report payload that follows the platform report contract."""
    return {
        "report_id": metadata.report_id,
        "schema_version": metadata.schema_version,
        "created_at": _utc_now(),
        "source_domain": metadata.source_domain,
        "project": metadata.project,
        "governance": {
            "model_version_id": metadata.model_version_id,
            "study_run_id": metadata.study_run_id,
        },
        "inputs": inputs or [],
        "artifacts": artifacts or [],
        "summary": summary or {},
        "validation": validation
        or {"valid": True, "errors": [], "warnings": []},
    }


def validate_report(payload: dict[str, Any]) -> list[str]:
    """Return contract validation errors for a report payload."""
    errors: list[str] = []
    for field_name in REQUIRED_REPORT_FIELDS:
        if field_name not in payload:
            errors.append(f"missing required field: {field_name}")
    if "report_id" in payload and not isinstance(payload["report_id"], str):
        errors.append("report_id must be a string")
    if "schema_version" in payload and payload["schema_version"] != SCHEMA_VERSION:
        errors.append(f"unsupported schema_version: {payload['schema_version']}")
    if "inputs" in payload and not isinstance(payload["inputs"], list):
        errors.append("inputs must be a list")
    if "artifacts" in payload and not isinstance(payload["artifacts"], list):
        errors.append("artifacts must be a list")
    if "summary" in payload and not isinstance(payload["summary"], dict):
        errors.append("summary must be an object")
    if "validation" in payload and not isinstance(payload["validation"], dict):
        errors.append("validation must be an object")
    return errors


def read_json_report(path: Path | str) -> dict[str, Any]:
    """Read a JSON report into a dictionary."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json_report(path: Path | str, payload: dict[str, Any]) -> Path:
    """Write a JSON report and return its path."""
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report_path


def write_report(
    path: Path | str,
    *,
    metadata: ReportMetadata,
    inputs: list[dict[str, Any]] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    summary: dict[str, Any] | None = None,
    validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build, validate, and write a platform report."""
    payload = build_report(
        metadata=metadata,
        inputs=inputs,
        artifacts=artifacts,
        summary=summary,
        validation=validation,
    )
    errors = validate_report(payload)
    if errors:
        raise ValueError("; ".join(errors))
    write_json_report(path, payload)
    return payload


def write_manifest(
    path: Path | str,
    *,
    reports: list[dict[str, Any]],
    root: Path | str | None = None,
    report_paths: dict[str, Path | str] | None = None,
) -> dict[str, Any]:
    """Write a compact manifest indexing platform reports by report_id."""
    root_path = Path(root) if root is not None else None
    locations = report_paths or {}
    manifest = {
        "manifest_id": "report_manifest",
        "schema_version": SCHEMA_VERSION,
        "created_at": _utc_now(),
        "report_count": len(reports),
        "reports": {
            report["report_id"]: _relative(Path(locations[report["report_id"]]), root_path)
            for report in reports
            if report.get("report_id") in locations
        },
        "report_ids": [report["report_id"] for report in reports],
        "validation": {
            "valid": all(not validate_report(report) for report in reports),
            "errors": {
                report["report_id"]: validate_report(report)
                for report in reports
                if validate_report(report)
            },
        },
    }
    write_json_report(path, manifest)
    return manifest


__all__ = [
    "ReportMetadata",
    "build_report",
    "file_reference",
    "read_json_report",
    "validate_report",
    "write_json_report",
    "write_manifest",
    "write_report",
]
