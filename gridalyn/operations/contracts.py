"""Contracts for utility flexibility operations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

OPERATION_SCHEMA_VERSION = "1.0"
PROVIDER_COLUMNS = [
    "provider_id",
    "scenario_id",
    "provider_type",
    "available_capacity_kw",
    "base_cost_per_kw_h",
    "selection_priority",
]
REQUIREMENT_COLUMNS = ["timestep", "constraint_id", "required_kw"]
SURROGATE_IMPACT_COLUMNS = [
    "provider_id",
    "scenario_id",
    "constraint_id",
    "predicted_deliverability_factor",
    "predicted_relief_kw",
    "selection_score",
]
TOPOLOGY_IMPACT_COLUMNS = [
    "provider_id",
    "scenario_id",
    "constraint_id",
    "sensitivity_kw_per_kw",
    "available_relief_kw",
]


@dataclass(frozen=True)
class FlexibilityOperationContext:
    """Identity and governance scope for a flexibility clearing operation."""

    operation_id: str
    scenario_id: str
    clearing_method: str
    dt_h: float
    model_version_id: str | None = None
    study_run_id: str | None = None
    schema_version: str = OPERATION_SCHEMA_VERSION
    source_domain: str = "operations.flexibility"
    market_role: str = "dso_flexibility_clearing"
    ontology_profile: str = "north_america"
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "schema_version": self.schema_version,
            "scenario_id": self.scenario_id,
            "clearing_method": self.clearing_method,
            "dt_h": float(self.dt_h),
            "source_domain": self.source_domain,
            "market_role": self.market_role,
            "ontology_profile": self.ontology_profile,
            "model_version_id": self.model_version_id,
            "study_run_id": self.study_run_id,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class FlexibilityOperationValidation:
    """Validation result for operation inputs."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": bool(self.valid),
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def build_operation_context(
    *,
    scenario_id: str,
    clearing_method: str,
    dt_h: float,
    requirements: pd.DataFrame,
    providers: pd.DataFrame,
    impact: pd.DataFrame,
    model_version_id: str | None = None,
    study_run_id: str | None = None,
) -> FlexibilityOperationContext:
    """Build a deterministic operation context from the operation scope."""
    method = _normalize_method(clearing_method)
    payload = {
        "schema_version": OPERATION_SCHEMA_VERSION,
        "scenario_id": str(scenario_id),
        "clearing_method": method,
        "dt_h": float(dt_h),
        "model_version_id": model_version_id,
        "study_run_id": study_run_id,
        "counts": {
            "requirements": int(len(requirements)),
            "providers": int(len(providers)),
            "impact": int(len(impact)),
        },
        "ids": {
            "constraints": _unique_values(requirements, "constraint_id"),
            "providers": _unique_values(providers, "provider_id"),
            "impact_constraints": _unique_values(impact, "constraint_id"),
        },
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return FlexibilityOperationContext(
        operation_id=f"operation:{scenario_id}:{method}:sha256:{digest}",
        scenario_id=str(scenario_id),
        clearing_method=method,
        dt_h=float(dt_h),
        model_version_id=model_version_id,
        study_run_id=study_run_id,
    )


def validate_flexibility_operation_inputs(
    *,
    requirements: pd.DataFrame,
    providers: pd.DataFrame,
    impact: pd.DataFrame,
    context: FlexibilityOperationContext,
) -> FlexibilityOperationValidation:
    """Validate the tabular inputs needed by the flexibility operation service."""
    errors: list[str] = []
    warnings: list[str] = []
    errors.extend(_missing_columns(requirements, REQUIREMENT_COLUMNS, "requirements"))
    errors.extend(_missing_columns(providers, PROVIDER_COLUMNS, "providers"))
    errors.extend(
        _missing_columns(
            impact,
            (
                SURROGATE_IMPACT_COLUMNS
                if context.clearing_method == "surrogate"
                else TOPOLOGY_IMPACT_COLUMNS
            ),
            "impact",
        )
    )
    if errors:
        return FlexibilityOperationValidation(
            valid=False, errors=errors, warnings=warnings
        )

    scenario_providers = providers.loc[
        providers["scenario_id"].astype(str) == context.scenario_id
    ]
    if scenario_providers.empty:
        errors.append(f"providers has no rows for scenario_id: {context.scenario_id}")
    scenario_impact = impact.loc[
        impact["scenario_id"].astype(str) == context.scenario_id
    ]
    if scenario_impact.empty:
        warnings.append(f"impact has no rows for scenario_id: {context.scenario_id}")

    if (requirements["required_kw"].astype(float) < 0.0).any():
        errors.append("requirements.required_kw must be non-negative")
    if (providers["available_capacity_kw"].astype(float) < 0.0).any():
        errors.append("providers.available_capacity_kw must be non-negative")
    if context.dt_h <= 0.0:
        errors.append("dt_h must be positive")

    provider_ids = set(scenario_providers["provider_id"].astype(str))
    impact_provider_ids = set(scenario_impact["provider_id"].astype(str))
    if (
        provider_ids
        and impact_provider_ids
        and not provider_ids.intersection(impact_provider_ids)
    ):
        warnings.append("impact has no provider_id overlap with scenario providers")

    return FlexibilityOperationValidation(
        valid=not errors,
        errors=errors,
        warnings=warnings,
    )


def _missing_columns(frame: pd.DataFrame, columns: list[str], label: str) -> list[str]:
    missing = [column for column in columns if column not in frame.columns]
    if not missing:
        return []
    return [f"{label} is missing required columns: {', '.join(missing)}"]


def _normalize_method(method: str) -> str:
    normalized = str(method).strip().lower()
    if normalized not in {"surrogate", "topology"}:
        raise ValueError("clearing_method must be 'surrogate' or 'topology'")
    return normalized


def _unique_values(frame: pd.DataFrame, column: str) -> list[str]:
    if column not in frame:
        return []
    return sorted(str(value) for value in frame[column].dropna().unique())
