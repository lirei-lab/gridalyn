"""Operational KPI reports for flexibility operations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from gridalyn.operations.contracts import FlexibilityOperationContext


def build_operational_kpi_report(
    *,
    events: pd.DataFrame,
    dispatch_instructions: pd.DataFrame,
    settlement_records: pd.DataFrame,
    constraints: pd.DataFrame,
    context: FlexibilityOperationContext,
    dt_h: float,
) -> dict[str, Any]:
    """Build mechanism-intelligence KPIs for an operation."""
    required_mwh = _mwh(events, "required_kw", dt_h)
    delivered_mwh = _mwh(events, "selected_relief_kw", dt_h)
    shortfall_mwh = _mwh(events, "shortfall_kw", dt_h)
    settlement_usd = (
        float(settlement_records["payment_usd"].astype(float).sum())
        if not settlement_records.empty and "payment_usd" in settlement_records
        else 0.0
    )
    summary = {
        "required_mwh": required_mwh,
        "delivered_mwh": delivered_mwh,
        "shortfall_mwh": shortfall_mwh,
        "delivery_ratio": _safe_div(delivered_mwh, required_mwh),
        "settlement_usd": settlement_usd,
        "cost_per_mwh_delivered": _safe_div(settlement_usd, delivered_mwh),
        "soft_selected_mwh": _mwh(events, "selected_soft_kw", dt_h),
        "hard_selected_mwh": _mwh(events, "selected_hard_kw", dt_h),
        "selected_provider_count": _nunique(dispatch_instructions, "provider_id"),
        "selected_aggregator_count": _nunique(dispatch_instructions, "aggregator_id"),
        "aggregator_concentration_top1_pct": _top1_share(
            dispatch_instructions, "aggregator_id", "expected_relief_kw"
        ),
        "topological_concentration_top1_pct": _top1_share(
            dispatch_instructions, "constraint_id", "expected_relief_kw"
        ),
        "active_constraint_count": int(len(constraints)),
        "constraint_count": _nunique(constraints, "constraint_id"),
        "max_severity_pctpt": _max_or_zero(constraints, "severity_pctpt"),
    }
    return {
        "report_id": "operational_kpi_report",
        "schema_version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "operation_id": context.operation_id,
        "scenario_id": context.scenario_id,
        "clearing_method": context.clearing_method,
        "governance": {
            "model_version_id": context.model_version_id,
            "study_run_id": context.study_run_id,
        },
        "summary": summary,
        "constraint_summary": _constraint_summary(events, constraints, dt_h),
    }


def _mwh(frame: pd.DataFrame, column: str, dt_h: float) -> float:
    if frame.empty or column not in frame:
        return 0.0
    return float(frame[column].astype(float).sum() * float(dt_h) / 1000.0)


def _safe_div(numerator: float, denominator: float) -> float | None:
    if abs(denominator) <= 1e-12:
        return None
    return float(numerator / denominator)


def _nunique(frame: pd.DataFrame, column: str) -> int:
    if frame.empty or column not in frame:
        return 0
    return int(frame[column].dropna().nunique())


def _top1_share(frame: pd.DataFrame, group_column: str, value_column: str) -> float | None:
    if frame.empty or group_column not in frame or value_column not in frame:
        return None
    grouped = frame.groupby(group_column)[value_column].sum().sort_values(ascending=False)
    total = float(grouped.sum())
    if total <= 1e-12:
        return None
    return float(grouped.iloc[0] / total)


def _max_or_zero(frame: pd.DataFrame, column: str) -> float:
    if frame.empty or column not in frame:
        return 0.0
    return float(frame[column].astype(float).max())


def _constraint_summary(
    events: pd.DataFrame,
    constraints: pd.DataFrame,
    dt_h: float,
) -> list[dict[str, Any]]:
    if constraints.empty:
        return []
    rows: list[dict[str, Any]] = []
    for constraint_id, group in constraints.groupby("constraint_id", sort=True):
        event_group = (
            events.loc[events["constraint_id"].astype(str) == str(constraint_id)]
            if not events.empty and "constraint_id" in events
            else pd.DataFrame()
        )
        rows.append(
            {
                "constraint_id": str(constraint_id),
                "active_event_count": int(len(group)),
                "required_mwh": _mwh(event_group, "required_kw", dt_h),
                "delivered_mwh": _mwh(event_group, "selected_relief_kw", dt_h),
                "shortfall_mwh": _mwh(event_group, "shortfall_kw", dt_h),
                "max_severity_pctpt": float(group["severity_pctpt"].astype(float).max()),
            }
        )
    return rows
