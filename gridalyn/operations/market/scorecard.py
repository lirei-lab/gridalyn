"""Benchmark flexibility clearing policies with common impact metrics."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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
    target = None if delivered is None and shortfall is None else (delivered or 0.0) + (shortfall or 0.0)
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
        "ext_grid_peak_reduction_mw": _num(comparison.get("ext_grid_peak_reduction_mw")),
        "v_min_improvement_pu": _num(comparison.get("v_min_improvement_pu")),
        "line_max_loading_reduction_pctpt": line_reduction,
        "trafo_max_loading_reduction_pctpt": trafo_reduction,
        "line_overload_delta": _int(comparison.get("line_overload_delta")),
        "trafo_overload_delta": _int(comparison.get("trafo_overload_delta")),
        "overload_reduction_count": _overload_reduction(comparison),
        "trafo_relief_pctpt_per_mwh": _safe_divide(trafo_reduction, delivered),
        "line_relief_pctpt_per_mwh": _safe_divide(line_reduction, delivered),
    }


def _comparison_vs_aggregate(policy: dict[str, Any], aggregate: dict[str, Any] | None) -> dict[str, float | int | None]:
    if not aggregate:
        return {}
    return {
        "delivered_delta_mwh": None
        if policy["total_delivered_mwh"] is None or aggregate["total_delivered_mwh"] is None
        else policy["total_delivered_mwh"] - aggregate["total_delivered_mwh"],
        "shortfall_delta_mwh": None
        if policy["total_shortfall_mwh"] is None or aggregate["total_shortfall_mwh"] is None
        else policy["total_shortfall_mwh"] - aggregate["total_shortfall_mwh"],
        "trafo_relief_delta_pctpt": None
        if policy["trafo_max_loading_reduction_pctpt"] is None
        or aggregate["trafo_max_loading_reduction_pctpt"] is None
        else policy["trafo_max_loading_reduction_pctpt"] - aggregate["trafo_max_loading_reduction_pctpt"],
        "overload_reduction_delta_count": None
        if policy["overload_reduction_count"] is None or aggregate["overload_reduction_count"] is None
        else policy["overload_reduction_count"] - aggregate["overload_reduction_count"],
        "v_min_improvement_delta_pu": None
        if policy["v_min_improvement_pu"] is None or aggregate["v_min_improvement_pu"] is None
        else policy["v_min_improvement_pu"] - aggregate["v_min_improvement_pu"],
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
    scenario_id = str(topology_report.get("scenario_id") or physics_report.get("scenario_id")) if physics_report else str(topology_report.get("scenario_id"))
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
    if locational_report and "locational_clearing" in locational_report.get("cases", {}):
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

    aggregate = next((policy for policy in policies if policy["policy_id"] == "aggregate_cls"), None)
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
        "best_transformer_relief_policy_id": _best_policy(policies, "trafo_max_loading_reduction_pctpt"),
        "best_overload_policy_id": _best_policy(policies, "overload_reduction_count"),
        "best_voltage_policy_id": _best_policy(policies, "v_min_improvement_pu"),
        "best_local_efficiency_policy_id": _best_policy(policies, "trafo_relief_pctpt_per_mwh"),
    }
    if market_report:
        summary["market_report_id"] = market_report.get("report_id")

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report_id": "flexibility_clearing_scorecard",
        "schema_version": "1.0",
        "scenario_id": scenario_id,
        "constraint_ids": topology_report.get("constraint_ids") or physics_report.get("constraint_ids") if physics_report else topology_report.get("constraint_ids", []),
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
