"""Governance contracts for model and project run traceability."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


GOVERNANCE_SCHEMA_VERSION = "1.0"


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ModelVersion:
    """Version contract for a digital-twin model snapshot."""

    id: str
    schema_version: str
    source_system: str
    source_adapter: str
    source_standard: str
    source_format: str
    artifact_hashes: dict[str, str | None]
    counts: dict[str, int]
    validation_status: str
    created_at: str
    lineage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "schema_version": self.schema_version,
            "source_system": self.source_system,
            "source_adapter": self.source_adapter,
            "source_standard": self.source_standard,
            "source_format": self.source_format,
            "artifact_hashes": self.artifact_hashes,
            "counts": self.counts,
            "validation_status": self.validation_status,
            "created_at": self.created_at,
            "lineage": self.lineage,
        }


@dataclass(frozen=True)
class StudyRun:
    """Run contract for a governed project workflow execution."""

    run_id: str
    schema_version: str
    project_id: str
    project_version: str
    workflow_id: str
    dry_run: bool
    status: str
    started_at: str
    ended_at: str | None
    git_commit: str | None
    stage_count: int
    completed_stage_count: int
    planned_stage_count: int
    failed_stage_count: int
    lineage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "project_version": self.project_version,
            "workflow_id": self.workflow_id,
            "dry_run": self.dry_run,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "git_commit": self.git_commit,
            "stage_count": self.stage_count,
            "completed_stage_count": self.completed_stage_count,
            "planned_stage_count": self.planned_stage_count,
            "failed_stage_count": self.failed_stage_count,
            "lineage": self.lineage,
        }


def build_model_version(
    *,
    source_system: str,
    source_adapter: str,
    source_standard: str,
    source_format: str,
    artifact_metadata: dict[str, dict[str, Any]],
    counts: dict[str, int],
    validation: dict[str, Any],
    lineage: dict[str, Any] | None = None,
    schema_version: str = GOVERNANCE_SCHEMA_VERSION,
    created_at: str | None = None,
) -> ModelVersion:
    """Build a deterministic model version from source lineage and artifacts."""
    artifact_hashes = {
        name: artifact.get("sha256")
        for name, artifact in sorted(artifact_metadata.items())
    }
    validation_status = "valid" if validation.get("valid", False) else "invalid"
    payload = {
        "artifact_hashes": artifact_hashes,
        "counts": counts,
        "lineage": lineage or {},
        "schema_version": schema_version,
        "source_adapter": source_adapter,
        "source_format": source_format,
        "source_standard": source_standard,
        "source_system": source_system,
        "validation_status": validation_status,
    }
    return ModelVersion(
        id=f"model:sha256:{_digest(payload)}",
        schema_version=schema_version,
        source_system=source_system,
        source_adapter=source_adapter,
        source_standard=source_standard,
        source_format=source_format,
        artifact_hashes=artifact_hashes,
        counts=dict(counts),
        validation_status=validation_status,
        created_at=created_at or utc_now(),
        lineage=lineage or {},
    )


def build_study_run(
    *,
    project_id: str,
    project_version: str,
    workflow_id: str,
    dry_run: bool,
    status: str,
    started_at: str,
    ended_at: str | None,
    git_commit: str | None,
    stages: list[dict[str, Any]],
    lineage: dict[str, Any] | None = None,
    schema_version: str = GOVERNANCE_SCHEMA_VERSION,
) -> StudyRun:
    """Build a governed project run summary from stage execution records."""
    completed = sum(1 for stage in stages if stage.get("status") == "completed")
    planned = sum(1 for stage in stages if stage.get("status") == "planned")
    failed = sum(1 for stage in stages if stage.get("status") == "failed")
    run_payload = {
        "dry_run": dry_run,
        "git_commit": git_commit,
        "project_id": project_id,
        "project_version": project_version,
        "schema_version": schema_version,
        "started_at": started_at,
        "workflow_id": workflow_id,
    }
    return StudyRun(
        run_id=f"run:{project_id}:{_digest(run_payload)[:16]}",
        schema_version=schema_version,
        project_id=project_id,
        project_version=project_version,
        workflow_id=workflow_id,
        dry_run=dry_run,
        status=status,
        started_at=started_at,
        ended_at=ended_at,
        git_commit=git_commit,
        stage_count=len(stages),
        completed_stage_count=completed,
        planned_stage_count=planned,
        failed_stage_count=failed,
        lineage=lineage or {},
    )


def _digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=_json_default).encode("utf-8")
    ).hexdigest()


def _json_default(value: Any) -> str:
    if isinstance(value, Path):
        return value.as_posix()
    return str(value)
