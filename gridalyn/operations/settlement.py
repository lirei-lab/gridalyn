"""Canonical flexibility settlement, KPI, and scorecard surface.

This module unifies three formerly separate sources behind the frozen
``gridalyn.operations`` facade (DOM-02 / DOM-03 / VERIF-01):

* the deterministic financial settlement engine
  (``calculate_period_settlement`` / :class:`AggregatorSettlementReceipt`),
  moved verbatim from ``gridalyn.operations.market.settlement`` — this is the
  **baseline source** (§4): the two-stage engine path
  (retired ``engine_mode``, tag ``archive/engine-mode-clearing``) called it to populate the
  committed ``market_settlement_cost`` / ``market_penalties`` baseline fields;
* the operational KPI report (``build_operational_kpi_report``), moved from
  ``gridalyn.operations.flexibility.kpis``;
* the clearing scorecard (``build_flexibility_clearing_scorecard`` /
  ``write_flexibility_clearing_scorecard``), moved from
  ``gridalyn.operations.market.scorecard``.

The separate ``build_settlement_records`` (in :mod:`gridalyn.operations.domain`)
backs the frozen entry point and is intentionally kept distinct from the
engine-path settlement reproduced here; its numbers feed ``payment_usd``, not
the committed baseline metrics.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from gridalyn.operations.contracts import FlexibilityOperationContext


@dataclass(frozen=True)
class AggregatorSettlementReceipt:
    """Immutable per-period settlement statement for an aggregator block."""

    block_id: int
    reservation_payment: float
    volume_cleared_kw: float
    penalty_deduction: float
    net_profit: float
    violation_kwh: float


def calculate_period_settlement(
    allocations_kw: dict[str, float],
    c_mcp_lambda: float,
    actual_p_meter_kw: float,
    dt_h: float,
    lambda_pen_penalty: float = 10.0,
    p_cap_limit_kw: float | None = None,
) -> AggregatorSettlementReceipt:
    """Evaluate baseline-free CLS settlement with deterministic AMI penalties.

    Pays the cleared limitation volume at the uniform clearing price and applies
    a structural penalty for any deterministic breach of the absolute power
    envelope (``P_cap``). This is the baseline-authoring settlement math (§4)
    and reproduces the committed numbers bit-for-bit.

    Args:
        allocations_kw: Cleared limitation volumes per accepted block (kW),
            derived deterministically from the contractual cap and the
            DSO-validated reference import at clearing time.
        c_mcp_lambda: Uniform market clearing price (lambda) in $/(kW*h).
        actual_p_meter_kw: Physical native-load telemetry captured during the
            window (kW).
        dt_h: Resolution of this telemetry check in hours (e.g. ``5 / 60`` for
            5-minute data).
        lambda_pen_penalty: Punitive cost ($/(kW*h)) for breaching the
            structural envelope. Defaults to ``10.0`` to anchor against the
            social cost of Hard CLS.
        p_cap_limit_kw: Absolute contractual cap recorded at clearing. Mainline
            settlement passes this explicitly so payments and penalties never
            depend on a reconstructed baseline.

    Returns:
        The immutable :class:`AggregatorSettlementReceipt` cash-flow statement.

    Raises:
        ValueError: If ``p_cap_limit_kw`` is ``None`` while the cleared volume
            is positive.
    """
    # 1. Pay the cleared limitation volume delta-P^soft at the uniform price.
    c_soft_cleared = sum(allocations_kw.values())

    revenue = c_soft_cleared * c_mcp_lambda * dt_h

    if c_soft_cleared <= 0:
        return AggregatorSettlementReceipt(
            block_id=-1,
            reservation_payment=0.0,
            volume_cleared_kw=0.0,
            penalty_deduction=0.0,
            net_profit=0.0,
            violation_kwh=0.0,
        )

    # 2. Strict deterministic boundary evaluation.
    if p_cap_limit_kw is None:
        raise ValueError("p_cap_limit_kw is required when cleared volume is positive")
    p_cap_limit = p_cap_limit_kw

    # Did the meter structurally breach the cap?
    breach_kw = max(0.0, actual_p_meter_kw - p_cap_limit)
    breach_kwh = breach_kw * dt_h

    # Apply the deterministic structural penalty, independent of baselines.
    penalty = breach_kwh * lambda_pen_penalty

    net = revenue - penalty

    return AggregatorSettlementReceipt(
        block_id=-1,  # Will be mapped externally.
        reservation_payment=revenue,
        volume_cleared_kw=c_soft_cleared,
        penalty_deduction=penalty,
        net_profit=net,
        violation_kwh=breach_kwh,
    )


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


def _top1_share(
    frame: pd.DataFrame, group_column: str, value_column: str
) -> float | None:
    if frame.empty or group_column not in frame or value_column not in frame:
        return None
    grouped = (
        frame.groupby(group_column)[value_column].sum().sort_values(ascending=False)
    )
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
                "max_severity_pctpt": float(
                    group["severity_pctpt"].astype(float).max()
                ),
            }
        )
    return rows


POLICY_LABELS = {
    "unmanaged": "Unmanaged",
    "aggregate_cls": "Aggregate CLS",
    "constraint_aware_clearing": "Constraint-Aware Clearing",
    "locational_clearing_verified": "Verified Locational Clearing",
    "topology_locational": "Topology Locational",
    "surrogate_locational": "Surrogate Locational",
    "physics_surrogate_locational": "Physics Surrogate Locational",
}


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _num(value)
    return None if number is None else int(number)


def _safe_divide(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or abs(denominator) < 1e-12:
        return None
    return float(numerator) / float(denominator)


def _comparison(report: dict[str, Any], case_id: str) -> dict[str, Any]:
    if case_id == "unmanaged":
        return {}
    return report.get("comparisons", {}).get(f"{case_id}_vs_unmanaged", {})


def _dispatch(report: dict[str, Any], case_id: str) -> dict[str, Any]:
    return report.get("dispatch", {}).get(case_id, {})


def _case(report: dict[str, Any], case_id: str) -> dict[str, Any]:
    return report.get("cases", {}).get(case_id, {})


def _overload_reduction(comparison: dict[str, Any]) -> int | None:
    trafo_delta = _int(comparison.get("trafo_overload_delta"))
    line_delta = _int(comparison.get("line_overload_delta"))
    if trafo_delta is None and line_delta is None:
        return None
    return max(-(trafo_delta or 0), 0) + max(-(line_delta or 0), 0)


def _policy_record(
    *,
    report: dict[str, Any],
    case_id: str,
    policy_id: str,
    intelligence_layer: str,
    source_report: str,
) -> dict[str, Any]:
    case = _case(report, case_id)
    dispatch = _dispatch(report, case_id)
    comparison = _comparison(report, case_id)
    delivered = _num(dispatch.get("total_delivered_mwh"))
    shortfall = _num(dispatch.get("total_shortfall_mwh"))
    target = (
        None
        if delivered is None and shortfall is None
        else (delivered or 0.0) + (shortfall or 0.0)
    )
    trafo_reduction = _num(comparison.get("trafo_max_loading_reduction_pctpt"))
    line_reduction = _num(comparison.get("line_max_loading_reduction_pctpt"))

    return {
        "policy_id": policy_id,
        "policy_label": POLICY_LABELS.get(policy_id, policy_id),
        "source_report": source_report,
        "source_case": case_id,
        "intelligence_layer": intelligence_layer,
        "total_delivered_mwh": delivered,
        "total_shortfall_mwh": shortfall,
        "delivery_ratio": _safe_divide(delivered, target),
        "soft_delivered_mwh": _num(dispatch.get("soft_delivered_mwh")),
        "hard_delivered_mwh": _num(dispatch.get("hard_delivered_mwh")),
        "shortfall_event_count": _int(dispatch.get("shortfall_event_count")),
        "ext_grid_peak_mw": _num(case.get("ext_grid_peak_mw")),
        "v_min_pu": _num(case.get("v_min_pu")),
        "line_max_loading_percent": _num(case.get("line_max_loading_percent")),
        "trafo_max_loading_percent": _num(case.get("trafo_max_loading_percent")),
        "n_line_overloads": _int(case.get("n_line_overloads")),
        "n_trafo_overloads": _int(case.get("n_trafo_overloads")),
        "ext_grid_peak_reduction_mw": _num(
            comparison.get("ext_grid_peak_reduction_mw")
        ),
        "v_min_improvement_pu": _num(comparison.get("v_min_improvement_pu")),
        "line_max_loading_reduction_pctpt": line_reduction,
        "trafo_max_loading_reduction_pctpt": trafo_reduction,
        "line_overload_delta": _int(comparison.get("line_overload_delta")),
        "trafo_overload_delta": _int(comparison.get("trafo_overload_delta")),
        "overload_reduction_count": _overload_reduction(comparison),
        "trafo_relief_pctpt_per_mwh": _safe_divide(trafo_reduction, delivered),
        "line_relief_pctpt_per_mwh": _safe_divide(line_reduction, delivered),
    }


def _comparison_vs_aggregate(
    policy: dict[str, Any], aggregate: dict[str, Any] | None
) -> dict[str, float | int | None]:
    if not aggregate:
        return {}
    return {
        "delivered_delta_mwh": (
            None
            if policy["total_delivered_mwh"] is None
            or aggregate["total_delivered_mwh"] is None
            else policy["total_delivered_mwh"] - aggregate["total_delivered_mwh"]
        ),
        "shortfall_delta_mwh": (
            None
            if policy["total_shortfall_mwh"] is None
            or aggregate["total_shortfall_mwh"] is None
            else policy["total_shortfall_mwh"] - aggregate["total_shortfall_mwh"]
        ),
        "trafo_relief_delta_pctpt": (
            None
            if policy["trafo_max_loading_reduction_pctpt"] is None
            or aggregate["trafo_max_loading_reduction_pctpt"] is None
            else policy["trafo_max_loading_reduction_pctpt"]
            - aggregate["trafo_max_loading_reduction_pctpt"]
        ),
        "overload_reduction_delta_count": (
            None
            if policy["overload_reduction_count"] is None
            or aggregate["overload_reduction_count"] is None
            else policy["overload_reduction_count"]
            - aggregate["overload_reduction_count"]
        ),
        "v_min_improvement_delta_pu": (
            None
            if policy["v_min_improvement_pu"] is None
            or aggregate["v_min_improvement_pu"] is None
            else policy["v_min_improvement_pu"] - aggregate["v_min_improvement_pu"]
        ),
    }


def _best_policy(
    policies: list[dict[str, Any]],
    metric: str,
    *,
    reverse: bool = True,
    tie_breaker: str | None = None,
) -> str | None:
    candidates = [policy for policy in policies if policy.get(metric) is not None]
    if not candidates:
        return None
    candidates.sort(
        key=lambda policy: (
            policy[metric],
            policy.get(tie_breaker) if tie_breaker else 0.0,
            policy["policy_id"],
        ),
        reverse=reverse,
    )
    return str(candidates[0]["policy_id"])


def build_flexibility_clearing_scorecard(
    *,
    topology_report: dict[str, Any],
    physics_report: dict[str, Any] | None = None,
    market_report: dict[str, Any] | None = None,
    locational_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a scenario scorecard from pandapower-validated policy reports."""
    scenario_id = (
        str(topology_report.get("scenario_id") or physics_report.get("scenario_id"))
        if physics_report
        else str(topology_report.get("scenario_id"))
    )
    policies = [
        _policy_record(
            report=topology_report,
            case_id="unmanaged",
            policy_id="unmanaged",
            intelligence_layer="none",
            source_report="topology_verification",
        ),
        _policy_record(
            report=topology_report,
            case_id="aggregate_cls",
            policy_id="aggregate_cls",
            intelligence_layer="aggregate_market",
            source_report="topology_verification",
        ),
    ]
    if "constraint_aware_clearing" in topology_report.get("cases", {}):
        policies.append(
            _policy_record(
                report=topology_report,
                case_id="constraint_aware_clearing",
                policy_id="constraint_aware_clearing",
                intelligence_layer="constraint_aware_market_v1",
                source_report="topology_verification",
            )
        )
    if locational_report and "locational_clearing" in locational_report.get(
        "cases", {}
    ):
        policies.append(
            _policy_record(
                report=locational_report,
                case_id="locational_clearing",
                policy_id="locational_clearing_verified",
                intelligence_layer="provider_selection_pandapower_replay",
                source_report="locational_clearing_verification",
            )
        )
    policies.append(
        _policy_record(
            report=topology_report,
            case_id="topology_locational",
            policy_id="topology_locational",
            intelligence_layer="grid_topology_heuristic",
            source_report="topology_verification",
        )
    )

    if "surrogate_locational" in topology_report.get("cases", {}):
        policies.append(
            _policy_record(
                report=topology_report,
                case_id="surrogate_locational",
                policy_id="surrogate_locational",
                intelligence_layer="topology_surrogate_v1",
                source_report="topology_verification",
            )
        )
    if physics_report and "surrogate_locational" in physics_report.get("cases", {}):
        policies.append(
            _policy_record(
                report=physics_report,
                case_id="surrogate_locational",
                policy_id="physics_surrogate_locational",
                intelligence_layer="physics_backed_surrogate_v1",
                source_report="physics_verification",
            )
        )

    aggregate = next(
        (policy for policy in policies if policy["policy_id"] == "aggregate_cls"), None
    )
    for policy in policies:
        policy["comparison_vs_aggregate"] = _comparison_vs_aggregate(policy, aggregate)

    policy_index = {policy["policy_id"]: policy for policy in policies}
    summary = {
        "policy_count": len(policies),
        "best_delivery_policy_id": _best_policy(policies, "total_delivered_mwh"),
        "best_delivery_ratio_policy_id": _best_policy(
            policies,
            "delivery_ratio",
            tie_breaker="total_delivered_mwh",
        ),
        "best_transformer_relief_policy_id": _best_policy(
            policies, "trafo_max_loading_reduction_pctpt"
        ),
        "best_overload_policy_id": _best_policy(policies, "overload_reduction_count"),
        "best_voltage_policy_id": _best_policy(policies, "v_min_improvement_pu"),
        "best_local_efficiency_policy_id": _best_policy(
            policies, "trafo_relief_pctpt_per_mwh"
        ),
    }
    if market_report:
        summary["market_report_id"] = market_report.get("report_id")

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report_id": "flexibility_clearing_scorecard",
        "schema_version": "1.0",
        "scenario_id": scenario_id,
        "constraint_ids": (
            topology_report.get("constraint_ids")
            or physics_report.get("constraint_ids")
            if physics_report
            else topology_report.get("constraint_ids", [])
        ),
        "baseline_policy_id": "aggregate_cls",
        "validation_authority": "pandapower_ac_powerflow",
        "summary": summary,
        "policies": policies,
        "policy_index": policy_index,
    }


def write_flexibility_clearing_scorecard(path: Path, scorecard: dict[str, Any]) -> Path:
    """Write a clearing scorecard JSON report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scorecard, indent=2, sort_keys=True))
    return path


__all__ = [
    "AggregatorSettlementReceipt",
    "build_flexibility_clearing_scorecard",
    "build_operational_kpi_report",
    "calculate_period_settlement",
    "write_flexibility_clearing_scorecard",
]
