"""Network constraint contracts for flexibility operations."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class NetworkConstraint:
    """Active network constraint that can be cleared by flexibility."""

    constraint_uid: str
    constraint_id: str
    scenario_id: str
    timestep: int
    timestamp: str | None
    constraint_type: str
    severity_kw: float
    severity_pctpt: float
    limit_value: float | None
    limit_unit: str | None
    observed_value: float | None
    observed_unit: str | None
    source: str
    model_version_id: str | None = None
    study_run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "constraint_uid": self.constraint_uid,
            "constraint_id": self.constraint_id,
            "scenario_id": self.scenario_id,
            "timestep": int(self.timestep),
            "timestamp": self.timestamp,
            "constraint_type": self.constraint_type,
            "severity_kw": float(self.severity_kw),
            "severity_pctpt": float(self.severity_pctpt),
            "limit_value": self.limit_value,
            "limit_unit": self.limit_unit,
            "observed_value": self.observed_value,
            "observed_unit": self.observed_unit,
            "source": self.source,
            "model_version_id": self.model_version_id,
            "study_run_id": self.study_run_id,
        }


def build_network_constraint_set(
    requirements: pd.DataFrame,
    *,
    scenario_id: str,
    source: str = "network_constraint_requirements",
    model_version_id: str | None = None,
    study_run_id: str | None = None,
) -> pd.DataFrame:
    """Normalize active requirement rows into a network constraint set."""
    if requirements.empty:
        return pd.DataFrame(columns=_constraint_columns())
    _require_columns(requirements, ["timestep", "constraint_id", "required_kw"])
    active = requirements.loc[requirements["required_kw"].astype(float) > 0.0].copy()
    rows: list[dict[str, Any]] = []
    for row in active.sort_values(["timestep", "constraint_id"]).to_dict("records"):
        constraint_id = str(row["constraint_id"])
        limit_value = _float_or_none(row.get("limit_percent"))
        observed_value = _float_or_none(row.get("loading_percent"))
        constraint = NetworkConstraint(
            constraint_uid=_stable_id(
                "constraint",
                scenario_id,
                constraint_id,
                row["timestep"],
                row.get("timestamp"),
            ),
            constraint_id=constraint_id,
            scenario_id=str(scenario_id),
            timestep=int(row["timestep"]),
            timestamp=str(row["timestamp"]) if pd.notna(row.get("timestamp")) else None,
            constraint_type=_constraint_type(constraint_id),
            severity_kw=float(row["required_kw"]),
            severity_pctpt=float(row.get("overload_pctpt", 0.0) or 0.0),
            limit_value=limit_value,
            limit_unit="percent" if limit_value is not None else None,
            observed_value=observed_value,
            observed_unit="percent" if observed_value is not None else None,
            source=str(source),
            model_version_id=model_version_id,
            study_run_id=study_run_id,
        )
        rows.append(constraint.to_dict())
    return pd.DataFrame(rows, columns=_constraint_columns())


def summarize_network_constraints(constraints: pd.DataFrame) -> dict[str, Any]:
    """Summarize a normalized network constraint set."""
    if constraints.empty:
        return {
            "active_constraint_count": 0,
            "constraint_count": 0,
            "total_required_kw": 0.0,
            "max_severity_pctpt": 0.0,
        }
    return {
        "active_constraint_count": int(len(constraints)),
        "constraint_count": int(constraints["constraint_id"].nunique()),
        "total_required_kw": float(constraints["severity_kw"].astype(float).sum()),
        "max_severity_pctpt": float(constraints["severity_pctpt"].astype(float).max()),
    }


def _constraint_type(constraint_id: str) -> str:
    if constraint_id.startswith("transformer:"):
        return "cim:PowerTransformer"
    if constraint_id.startswith("line:"):
        return "cim:ACLineSegment"
    if constraint_id.startswith("bus:"):
        return "cim:ConnectivityNode"
    return "dt:NetworkConstraint"


def _float_or_none(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _stable_id(prefix: str, *parts: Any) -> str:
    payload = json.dumps([str(part) for part in parts], sort_keys=True)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{prefix}:sha256:{digest}"


def _require_columns(frame: pd.DataFrame, columns: list[str]) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(
            f"requirements is missing required columns: {', '.join(missing)}"
        )


def _constraint_columns() -> list[str]:
    return [
        "constraint_uid",
        "constraint_id",
        "scenario_id",
        "timestep",
        "timestamp",
        "constraint_type",
        "severity_kw",
        "severity_pctpt",
        "limit_value",
        "limit_unit",
        "observed_value",
        "observed_unit",
        "source",
        "model_version_id",
        "study_run_id",
    ]
