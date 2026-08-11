"""Network impact verification report for locational flexibility policies."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from gridalyn.simulation.surrogates.contract import ErrorBound


def _require_columns(frame: pd.DataFrame, columns: list[str], label: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{label} is missing required columns: {missing}")


def _scenario_filter(frame: pd.DataFrame, scenario_id: str) -> pd.DataFrame:
    if "scenario_id" not in frame:
        return frame.copy()
    return frame.loc[frame["scenario_id"] == scenario_id].copy()


def build_provider_ranking(
    providers: pd.DataFrame,
    *,
    scenario_id: str,
    constraint_ids: list[str],
    method: str,
    sensitivity: pd.DataFrame | None = None,
    predictions: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build a provider ranking for topology-only or surrogate selection."""
    _require_columns(
        providers,
        [
            "provider_id",
            "scenario_id",
            "provider_type",
            "pandapower_load",
            "available_capacity_kw",
            "base_cost_per_kw_h",
            "selection_priority",
        ],
        "providers",
    )
    scenario_providers = _scenario_filter(providers, scenario_id)
    constraints = set(str(value) for value in constraint_ids)

    if method == "surrogate":
        if predictions is None:
            raise ValueError("predictions is required for surrogate ranking")
        _require_columns(
            predictions,
            [
                "provider_id",
                "scenario_id",
                "constraint_id",
                "predicted_deliverability_factor",
                "predicted_relief_kw",
                "selection_score",
            ],
            "predictions",
        )
        impact = _scenario_filter(predictions, scenario_id)
        impact = impact.loc[
            impact["constraint_id"].astype(str).isin(constraints)
            & (impact["predicted_deliverability_factor"].astype(float) > 0.0)
        ].copy()
        impact = impact.drop(
            columns=[
                column
                for column in [
                    "available_capacity_kw",
                    "base_cost_per_kw_h",
                    "selection_priority",
                ]
                if column in impact.columns
            ]
        )
        merged = scenario_providers.merge(
            impact,
            on=["provider_id", "scenario_id", "provider_type"],
            how="inner",
            validate="one_to_many",
        )
        if merged.empty:
            return merged
        merged["rank_score"] = merged["selection_score"].astype(float)
        merged["expected_relief_kw"] = merged["predicted_relief_kw"].astype(float)
        merged["deliverability_factor"] = merged[
            "predicted_deliverability_factor"
        ].astype(float)
    elif method == "topology":
        if sensitivity is None:
            raise ValueError("sensitivity is required for topology ranking")
        _require_columns(
            sensitivity,
            [
                "provider_id",
                "scenario_id",
                "constraint_id",
                "sensitivity_kw_per_kw",
                "available_relief_kw",
            ],
            "sensitivity",
        )
        impact = _scenario_filter(sensitivity, scenario_id)
        impact = impact.loc[
            impact["constraint_id"].astype(str).isin(constraints)
            & (impact["sensitivity_kw_per_kw"].astype(float) > 0.0)
        ].copy()
        merged = scenario_providers.merge(
            impact,
            on=["provider_id", "scenario_id"],
            how="inner",
            validate="one_to_many",
        )
        if merged.empty:
            return merged
        merged["deliverability_factor"] = merged["sensitivity_kw_per_kw"].astype(float)
        merged["expected_relief_kw"] = merged["available_relief_kw"].astype(float)
        merged["rank_score"] = merged["expected_relief_kw"] / (
            merged["base_cost_per_kw_h"].astype(float).clip(lower=0.001)
            * merged["selection_priority"].astype(float).clip(lower=1.0)
        )
    else:
        raise ValueError("method must be 'topology' or 'surrogate'")

    merged = merged.sort_values(
        ["provider_id", "rank_score", "expected_relief_kw"],
        ascending=[True, False, False],
    ).drop_duplicates("provider_id", keep="first")
    columns = [
        "provider_id",
        "scenario_id",
        "provider_type",
        "pandapower_load",
        "constraint_id",
        "available_capacity_kw",
        "base_cost_per_kw_h",
        "selection_priority",
        "deliverability_factor",
        "expected_relief_kw",
        "rank_score",
    ]
    return (
        merged[columns]
        .sort_values(
            ["rank_score", "expected_relief_kw", "provider_id"],
            ascending=[False, False, True],
        )
        .reset_index(drop=True)
    )


def _allocate_ranked_reduction(
    load_kw: np.ndarray,
    target_kw: np.ndarray,
    ranking: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    managed = np.asarray(load_kw, dtype=float).copy()
    target = np.asarray(target_kw, dtype=float)
    curtailed = np.zeros_like(managed)
    delivered = np.zeros(managed.shape[0], dtype=float)
    shortfall = np.zeros(managed.shape[0], dtype=float)
    if target.shape != (managed.shape[0],):
        raise ValueError("target_kw must have one value per timestep")
    if ranking.empty:
        shortfall = np.maximum(target, 0.0)
        return managed, delivered, shortfall

    ordered = ranking.sort_values(
        ["rank_score", "expected_relief_kw", "provider_id"],
        ascending=[False, False, True],
    )
    provider_rows = ordered.to_dict("records")
    for t in range(managed.shape[0]):
        remaining = max(float(target[t]), 0.0)
        for provider in provider_rows:
            if remaining <= 1e-9:
                break
            load_idx = int(provider["pandapower_load"])
            if load_idx < 0 or load_idx >= managed.shape[1]:
                continue
            capacity_kw = max(float(provider["available_capacity_kw"]), 0.0)
            reduction = min(remaining, capacity_kw, managed[t, load_idx])
            if reduction <= 0.0:
                continue
            managed[t, load_idx] -= reduction
            curtailed[t, load_idx] += reduction
            delivered[t] += reduction
            remaining -= reduction
        shortfall[t] = max(remaining, 0.0)
    return managed, delivered, shortfall


def build_constraint_requirements(
    *,
    transformer_timeseries: pd.DataFrame,
    transformer_id_by_idx: dict[int, str],
    constraint_ids: list[str],
    limit_percent: float = 100.0,
) -> pd.DataFrame:
    """Convert transformer loading above a limit into local kW requirements."""
    _require_columns(
        transformer_timeseries,
        ["timestamp", "trafo_idx", "loading_percent", "sn_mva"],
        "transformer_timeseries",
    )
    constraints = set(str(value) for value in constraint_ids)
    rows: list[dict[str, Any]] = []
    frame = transformer_timeseries.copy()
    frame["constraint_id"] = frame["trafo_idx"].map(
        lambda value: transformer_id_by_idx.get(int(value))
    )
    frame = frame.loc[frame["constraint_id"].astype(str).isin(constraints)].copy()
    frame = frame.sort_values(["timestamp", "constraint_id"]).reset_index(drop=True)
    timestep_by_timestamp = {
        timestamp: index
        for index, timestamp in enumerate(frame["timestamp"].drop_duplicates().tolist())
    }
    for row in frame.to_dict("records"):
        loading = float(row["loading_percent"])
        overload_pctpt = max(loading - float(limit_percent), 0.0)
        sn_mva = float(row["sn_mva"])
        rows.append(
            {
                "timestep": int(timestep_by_timestamp[row["timestamp"]]),
                "timestamp": row["timestamp"],
                "constraint_id": str(row["constraint_id"]),
                "loading_percent": loading,
                "limit_percent": float(limit_percent),
                "overload_pctpt": overload_pctpt,
                "sn_mva": sn_mva,
                "required_kw": overload_pctpt / 100.0 * sn_mva * 1000.0,
            }
        )
    return pd.DataFrame(rows)


def build_constraint_aware_dispatch(
    *,
    building_kw: np.ndarray,
    ev_kw: np.ndarray,
    requirements: pd.DataFrame,
    provider_ranking: pd.DataFrame,
) -> dict[str, Any]:
    """Clear local transformer requirements with local providers, Soft first."""
    building = np.asarray(building_kw, dtype=float).copy()
    ev = np.asarray(ev_kw, dtype=float).copy()
    if building.shape != ev.shape:
        raise ValueError("building_kw and ev_kw must have matching shapes")
    _require_columns(
        requirements, ["timestep", "constraint_id", "required_kw"], "requirements"
    )
    _require_columns(
        provider_ranking,
        [
            "provider_id",
            "provider_type",
            "pandapower_load",
            "constraint_id",
            "available_capacity_kw",
            "rank_score",
        ],
        "provider_ranking",
    )

    n_steps = building.shape[0]
    soft_delivered = np.zeros(n_steps, dtype=float)
    hard_delivered = np.zeros(n_steps, dtype=float)
    shortfall = np.zeros(n_steps, dtype=float)
    events: list[dict[str, Any]] = []

    ranking = provider_ranking.copy()
    ranking["provider_priority"] = np.where(
        ranking["provider_type"] == "soft_cls_building",
        0,
        1,
    )
    ranking = ranking.sort_values(
        [
            "constraint_id",
            "provider_priority",
            "rank_score",
            "expected_relief_kw",
            "provider_id",
        ],
        ascending=[True, True, False, False, True],
    )

    active_requirements = requirements.loc[
        requirements["required_kw"].astype(float) > 0.0
    ].sort_values(["timestep", "required_kw"], ascending=[True, False])

    for requirement in active_requirements.to_dict("records"):
        timestep = int(requirement["timestep"])
        if timestep < 0 or timestep >= n_steps:
            continue
        constraint_id = str(requirement["constraint_id"])
        remaining = float(requirement["required_kw"])
        selected_soft = 0.0
        selected_hard = 0.0
        selected_providers: list[dict[str, Any]] = []
        candidates = ranking.loc[ranking["constraint_id"].astype(str) == constraint_id]

        for provider in candidates.to_dict("records"):
            if remaining <= 1e-9:
                break
            load_idx = int(provider["pandapower_load"])
            if load_idx < 0 or load_idx >= building.shape[1]:
                continue
            capacity_kw = max(float(provider["available_capacity_kw"]), 0.0)
            provider_type = str(provider["provider_type"])
            if provider_type == "soft_cls_building":
                available_kw = max(building[timestep, load_idx], 0.0)
                reduction = min(remaining, capacity_kw, available_kw)
                building[timestep, load_idx] -= reduction
                soft_delivered[timestep] += reduction
                selected_soft += reduction
            elif provider_type == "hard_cls_ev":
                available_kw = max(ev[timestep, load_idx], 0.0)
                reduction = min(remaining, capacity_kw, available_kw)
                ev[timestep, load_idx] -= reduction
                hard_delivered[timestep] += reduction
                selected_hard += reduction
            else:
                continue
            if reduction <= 0.0:
                continue
            remaining -= reduction
            selected_providers.append(
                {
                    "provider_id": provider["provider_id"],
                    "provider_type": provider_type,
                    "selected_kw": float(reduction),
                    "rank_score": float(provider["rank_score"]),
                }
            )

        final_shortfall = max(remaining, 0.0)
        shortfall[timestep] += final_shortfall
        events.append(
            {
                "timestep": timestep,
                "timestamp": requirement.get("timestamp"),
                "constraint_id": constraint_id,
                "required_kw": float(requirement["required_kw"]),
                "selected_soft_kw": float(selected_soft),
                "selected_hard_kw": float(selected_hard),
                "selected_relief_kw": float(selected_soft + selected_hard),
                "local_shortfall_kw": float(final_shortfall),
                "selected_provider_count": len(selected_providers),
                "selected_providers": selected_providers[:20],
            }
        )

    return {
        "managed_building_kw": building,
        "managed_ev_kw": ev,
        "soft_delivered_kw": soft_delivered,
        "hard_delivered_kw": hard_delivered,
        "soft_shortfall_kw": np.zeros(n_steps, dtype=float),
        "hard_shortfall_kw": shortfall,
        "shortfall_kw": shortfall,
        "events": events,
    }


def build_locational_dispatch(
    *,
    building_kw: np.ndarray,
    ev_kw: np.ndarray,
    soft_target_kw: np.ndarray,
    hard_target_kw: np.ndarray,
    provider_ranking: pd.DataFrame,
) -> dict[str, np.ndarray]:
    """Apply aggregate soft/hard targets to ranked local providers."""
    building = np.asarray(building_kw, dtype=float)
    ev = np.asarray(ev_kw, dtype=float)
    if building.shape != ev.shape:
        raise ValueError("building_kw and ev_kw must have matching shapes")

    soft_ranking = provider_ranking.loc[
        provider_ranking["provider_type"] == "soft_cls_building"
    ].copy()
    hard_ranking = provider_ranking.loc[
        provider_ranking["provider_type"] == "hard_cls_ev"
    ].copy()
    managed_building, soft_delivered, soft_shortfall = _allocate_ranked_reduction(
        building,
        soft_target_kw,
        soft_ranking,
    )
    managed_ev, hard_delivered, hard_shortfall = _allocate_ranked_reduction(
        ev,
        hard_target_kw,
        hard_ranking,
    )
    return {
        "managed_building_kw": managed_building,
        "managed_ev_kw": managed_ev,
        "soft_delivered_kw": soft_delivered,
        "hard_delivered_kw": hard_delivered,
        "soft_shortfall_kw": soft_shortfall,
        "hard_shortfall_kw": hard_shortfall,
    }


def summarize_dispatch(
    *,
    soft_delivered_kw: np.ndarray,
    hard_delivered_kw: np.ndarray,
    soft_shortfall_kw: np.ndarray,
    hard_shortfall_kw: np.ndarray,
    dt_h: float,
) -> dict[str, float]:
    """Summarize dispatch delivery and local shortfall in MWh."""
    soft_delivered = np.asarray(soft_delivered_kw, dtype=float)
    hard_delivered = np.asarray(hard_delivered_kw, dtype=float)
    soft_shortfall = np.asarray(soft_shortfall_kw, dtype=float)
    hard_shortfall = np.asarray(hard_shortfall_kw, dtype=float)
    return {
        "soft_delivered_mwh": float(soft_delivered.sum() * dt_h / 1000.0),
        "hard_delivered_mwh": float(hard_delivered.sum() * dt_h / 1000.0),
        "total_delivered_mwh": float(
            (soft_delivered.sum() + hard_delivered.sum()) * dt_h / 1000.0
        ),
        "soft_shortfall_mwh": float(soft_shortfall.sum() * dt_h / 1000.0),
        "hard_shortfall_mwh": float(hard_shortfall.sum() * dt_h / 1000.0),
        "total_shortfall_mwh": float(
            (soft_shortfall.sum() + hard_shortfall.sum()) * dt_h / 1000.0
        ),
        "shortfall_event_count": int(np.sum((soft_shortfall + hard_shortfall) > 1e-9)),
    }


def _compare_to_unmanaged(
    metrics: dict[str, Any], unmanaged: dict[str, Any]
) -> dict[str, float | int]:
    return {
        "trafo_max_loading_reduction_pctpt": float(
            unmanaged["trafo_max_loading_percent"]
            - metrics["trafo_max_loading_percent"]
        ),
        "line_max_loading_reduction_pctpt": float(
            unmanaged["line_max_loading_percent"] - metrics["line_max_loading_percent"]
        ),
        "v_min_improvement_pu": float(metrics["v_min_pu"] - unmanaged["v_min_pu"]),
        "ext_grid_peak_reduction_mw": float(
            unmanaged["ext_grid_peak_mw"] - metrics["ext_grid_peak_mw"]
        ),
        "trafo_overload_delta": int(
            metrics["n_trafo_overloads"] - unmanaged["n_trafo_overloads"]
        ),
        "line_overload_delta": int(
            metrics["n_line_overloads"] - unmanaged["n_line_overloads"]
        ),
    }


def build_network_impact_verification_report(
    *,
    scenario_id: str,
    constraint_ids: list[str],
    case_metrics: dict[str, dict[str, Any]],
    dispatch_summaries: dict[str, dict[str, Any]],
    surrogate_error_bounds: Mapping[str, ErrorBound] | None = None,
) -> dict[str, Any]:
    """Build the canonical network-impact verification report.

    Args:
        scenario_id: Scenario the cases were solved for.
        constraint_ids: Constraints the dispatch targeted.
        case_metrics: Solved metrics per case; must include ``unmanaged``.
        dispatch_summaries: Delivery/shortfall summaries per case.
        surrogate_error_bounds: Stated accuracy of the surrogates whose
            rankings fed the dispatch, keyed by surrogate ID. Omitted from the
            payload when ``None``, so an existing caller's report is
            unchanged; supply it to make the screening accuracy part of the
            verification record rather than folklore.

    Returns:
        The verification report payload.

    Raises:
        ValueError: If ``case_metrics`` has no ``unmanaged`` baseline to
            compare the managed cases against.
    """
    if "unmanaged" not in case_metrics:
        raise ValueError("case_metrics must include an unmanaged baseline")
    comparisons = {}
    unmanaged = case_metrics["unmanaged"]
    for label, metrics in case_metrics.items():
        if label == "unmanaged":
            continue
        comparisons[f"{label}_vs_unmanaged"] = _compare_to_unmanaged(metrics, unmanaged)

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report_id": "network_impact_verification",
        "schema_version": "1.0",
        "scenario_id": scenario_id,
        "constraint_ids": constraint_ids,
        "validation": {
            "authority": "pandapower_ac_powerflow",
            "policy": "surrogate_and_topology_rankings_are_screening_inputs_only",
        },
        "cases": case_metrics,
        "dispatch": dispatch_summaries,
        "comparisons": comparisons,
    }
    if surrogate_error_bounds is not None:
        report["surrogate_error_bounds"] = {
            surrogate_id: bound.as_dict()
            for surrogate_id, bound in sorted(surrogate_error_bounds.items())
        }
    return report


def write_network_impact_verification_report(
    path: Path, report: dict[str, Any]
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True))
    return path
