"""Canonical operation run contracts for utility-facing workflows."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


OPERATION_RUN_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class OperationRunValidation:
    """Validation result for an operation run document."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": bool(self.valid),
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class OperationRun:
    """Traceable execution record for a utility operation."""

    operation_id: str
    operation_type: str
    scenario_id: str
    network_model_version_id: str
    study_run_id: str | None
    input_artifacts: dict[str, str]
    output_artifacts: dict[str, str]
    kpi_report: str
    clearing_method: str | None = None
    status: str = "completed"
    validation: dict[str, Any] = field(
        default_factory=lambda: {"valid": True, "errors": [], "warnings": []}
    )
    metrics: dict[str, Any] = field(default_factory=dict)
    governance: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    schema_version: str = OPERATION_RUN_SCHEMA_VERSION
    report_id: str = "operation_run"

    def to_dict(self) -> dict[str, Any]:
        governance = {
            "network_model_version_id": self.network_model_version_id,
            "study_run_id": self.study_run_id,
            **self.governance,
        }
        return {
            "report_id": self.report_id,
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "operation_id": self.operation_id,
            "operation_type": self.operation_type,
            "scenario_id": self.scenario_id,
            "status": self.status,
            "clearing_method": self.clearing_method,
            "governance": governance,
            "input_artifacts": dict(self.input_artifacts),
            "output_artifacts": dict(self.output_artifacts),
            "kpi_report": self.kpi_report,
            "validation": dict(self.validation),
            "metrics": dict(self.metrics),
        }


def build_operation_run(
    *,
    operation_id: str,
    operation_type: str,
    scenario_id: str,
    network_model_version_id: str,
    study_run_id: str | None,
    input_artifacts: dict[str, str],
    output_artifacts: dict[str, str],
    kpi_report: str,
    clearing_method: str | None = None,
    status: str = "completed",
    validation: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    governance: dict[str, Any] | None = None,
) -> OperationRun:
    """Build an operation run record from operation lineage and outputs."""
    return OperationRun(
        operation_id=str(operation_id),
        operation_type=str(operation_type),
        scenario_id=str(scenario_id),
        network_model_version_id=str(network_model_version_id),
        study_run_id=str(study_run_id) if study_run_id else None,
        clearing_method=str(clearing_method) if clearing_method else None,
        status=str(status),
        input_artifacts={str(key): str(value) for key, value in input_artifacts.items()},
        output_artifacts={
            str(key): str(value) for key, value in output_artifacts.items()
        },
        kpi_report=str(kpi_report),
        validation=validation or {"valid": True, "errors": [], "warnings": []},
        metrics=metrics or {},
        governance=governance or {},
    )


def validate_operation_run(run: OperationRun | dict[str, Any]) -> OperationRunValidation:
    """Validate the minimal lineage required for an operation run."""
    payload = run.to_dict() if isinstance(run, OperationRun) else dict(run)
    errors: list[str] = []
    warnings: list[str] = []

    for field_name in ("operation_id", "operation_type", "scenario_id", "status"):
        if not payload.get(field_name):
            errors.append(f"{field_name} is required")

    governance = payload.get("governance") or {}
    if not governance.get("network_model_version_id"):
        errors.append("governance.network_model_version_id is required")

    if not isinstance(payload.get("input_artifacts"), dict) or not payload.get(
        "input_artifacts"
    ):
        errors.append("input_artifacts must not be empty")
    if not isinstance(payload.get("output_artifacts"), dict) or not payload.get(
        "output_artifacts"
    ):
        errors.append("output_artifacts must not be empty")
    if not payload.get("kpi_report"):
        errors.append("kpi_report is required")

    validation = payload.get("validation") or {}
    if validation and validation.get("valid") is False:
        warnings.append("operation_run.validation is false")

    return OperationRunValidation(valid=not errors, errors=errors, warnings=warnings)


def write_operation_run(path: Path, run: OperationRun | dict[str, Any]) -> Path:
    """Write an operation run JSON document."""
    payload = run.to_dict() if isinstance(run, OperationRun) else dict(run)
    validation = validate_operation_run(payload)
    if not validation.valid:
        raise ValueError("; ".join(validation.errors))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path
