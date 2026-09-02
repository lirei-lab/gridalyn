"""Public report helpers and JSON report contract."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    """Identity and provenance header for a platform report.

    Every artifact-producing run emits a report through :func:`write_report`,
    and this frozen record supplies the non-payload half of that envelope: what
    the report is called, which domain produced it, and the governance ids that
    let a result be traced back to the model version and study run it came from.

    Attributes:
        report_id: Stable identifier for this report within its domain.
        source_domain: Producing layer or domain, e.g. ``"simulation"``.
        schema_version: Report contract version; defaults to
            :data:`SCHEMA_VERSION`.
        project: Project descriptor (name, paths) carried into the envelope.
        model_version_id: Governance id of the model version used, if tracked.
        study_run_id: Governance id tying this report to one study run.
    """

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
    uncertainty: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a report payload that follows the platform report contract.

    Args:
        metadata: Identity and provenance header for the report.
        inputs: Input provenance records.
        artifacts: Artifact provenance records.
        summary: The run's headline numbers.
        validation: The run's own pass/fail payload.
        uncertainty: Optional intervals qualifying headline numbers in
            ``summary``, keyed by metric name. Build it with
            :func:`gridalyn.foundation.platform.uncertainty.build_uncertainty`
            rather than by hand. Omitted from the payload when absent -- an
            empty block is a contract error, not a neutral default.

    Returns:
        The report payload.

    Raises:
        ValueError: If ``uncertainty`` is given but does not satisfy the
            contract, naming each failing field.
    """
    if uncertainty is not None:
        from gridalyn.foundation.platform.uncertainty import validate_uncertainty

        problems = validate_uncertainty(uncertainty, summary or {})
        if problems:
            raise ValueError(
                f"{metadata.report_id}: invalid uncertainty block: "
                + "; ".join(problems)
            )
    payload = {
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
        "validation": validation or {"valid": True, "errors": [], "warnings": []},
    }
    if uncertainty is not None:
        payload["uncertainty"] = uncertainty
    return payload


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
    if "uncertainty" in payload:
        from gridalyn.foundation.platform.uncertainty import validate_uncertainty

        errors.extend(
            validate_uncertainty(payload["uncertainty"], payload.get("summary"))
        )
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
    uncertainty: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build, validate, and write a platform report.

    Args:
        path: Destination for the JSON report.
        metadata: Identity and provenance header.
        inputs: Input provenance records.
        artifacts: Artifact provenance records.
        summary: The run's headline numbers.
        validation: The run's own pass/fail payload.
        uncertainty: Optional intervals qualifying entries of ``summary``.

    Returns:
        The written payload.

    Raises:
        ValueError: If the assembled payload violates the report contract.
    """
    payload = build_report(
        metadata=metadata,
        inputs=inputs,
        artifacts=artifacts,
        summary=summary,
        validation=validation,
        uncertainty=uncertainty,
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
            report["report_id"]: _relative(
                Path(locations[report["report_id"]]), root_path
            )
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
