"""Locational flexibility clearing over digital-twin provider offers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


EVENT_COLUMNS = [
    "event_id",
    "scenario_id",
    "timestep",
    "timestamp",
    "constraint_id",
    "required_kw",
    "selected_relief_kw",
    "selected_soft_kw",
    "selected_hard_kw",
    "shortfall_kw",
    "selected_provider_count",
    "estimated_cost",
    "overload_pctpt",
    "clearing_method",
]

SELECTION_COLUMNS = [
    "event_id",
    "scenario_id",
    "timestep",
    "timestamp",
    "constraint_id",
    "provider_id",
    "provider_type",
    "selected_kw",
    "expected_relief_kw",
    "deliverability_factor",
    "rank_score",
    "effective_cost_per_relief_kw_h",
    "estimated_cost",
]


def _require_columns(frame: pd.DataFrame, columns: list[str], label: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{label} is missing required columns: {', '.join(missing)}")


def _provider_priority(provider_type: str) -> int:
    return 0 if provider_type == "soft_cls_building" else 1


def _json_default(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


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


def _prepare_candidates(
    *,
    providers: pd.DataFrame,
    impact: pd.DataFrame,
    scenario_id: str,
    clearing_method: str,
) -> pd.DataFrame:
    _require_columns(
        providers,
        [
            "provider_id",
            "scenario_id",
            "provider_type",
            "available_capacity_kw",
            "base_cost_per_kw_h",
            "selection_priority",
        ],
        "providers",
    )
    scenario_providers = providers.loc[providers["scenario_id"].astype(str) == scenario_id].copy()

    if clearing_method == "surrogate":
        _require_columns(
            impact,
            [
                "provider_id",
                "scenario_id",
                "constraint_id",
                "predicted_deliverability_factor",
                "predicted_relief_kw",
                "selection_score",
            ],
            "impact",
        )
        impact_frame = impact.loc[impact["scenario_id"].astype(str) == scenario_id].copy()
        impact_frame["deliverability_factor"] = impact_frame[
            "predicted_deliverability_factor"
        ].astype(float)
        impact_frame["expected_capacity_relief_kw"] = impact_frame[
            "predicted_relief_kw"
        ].astype(float)
        impact_frame["rank_score"] = impact_frame["selection_score"].astype(float)
    elif clearing_method == "topology":
        _require_columns(
            impact,
            [
                "provider_id",
                "scenario_id",
                "constraint_id",
                "sensitivity_kw_per_kw",
                "available_relief_kw",
            ],
            "impact",
        )
        impact_frame = impact.loc[impact["scenario_id"].astype(str) == scenario_id].copy()
        impact_frame["deliverability_factor"] = impact_frame["sensitivity_kw_per_kw"].astype(float)
        impact_frame["expected_capacity_relief_kw"] = impact_frame["available_relief_kw"].astype(float)
        impact_frame["rank_score"] = impact_frame["expected_capacity_relief_kw"] / (
            impact_frame.get("base_cost_per_kw_h", 1.0).astype(float).clip(lower=0.001)
            if "base_cost_per_kw_h" in impact_frame
            else 1.0
        )
    else:
        raise ValueError("clearing_method must be 'surrogate' or 'topology'")

    impact_source_columns = [
        "provider_id",
        "scenario_id",
        "constraint_id",
        "deliverability_factor",
        "expected_capacity_relief_kw",
        "rank_score",
    ]
    candidates = scenario_providers.merge(
        impact_frame[impact_source_columns],
        on=["provider_id", "scenario_id"],
        how="inner",
        validate="one_to_many",
    )
    if candidates.empty:
        return candidates
    candidates = candidates.loc[
        (candidates["deliverability_factor"].astype(float) > 0.0)
        & (candidates["expected_capacity_relief_kw"].astype(float) > 0.0)
    ].copy()
    if candidates.empty:
        return candidates
    candidates["provider_priority"] = candidates["provider_type"].map(_provider_priority)
    candidates["effective_cost_per_relief_kw_h"] = (
        candidates["base_cost_per_kw_h"].astype(float)
        / candidates["deliverability_factor"].astype(float).clip(lower=1e-9)
    )
    return candidates


def build_locational_clearing(
    *,
    requirements: pd.DataFrame,
    providers: pd.DataFrame,
    impact: pd.DataFrame,
    scenario_id: str,
    dt_h: float,
    clearing_method: str = "surrogate",
    max_selected_providers_per_event: int = 1000,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Clear transformer-level requirements with locational provider offers."""
    _require_columns(
        requirements,
        ["timestep", "constraint_id", "required_kw"],
        "requirements",
    )
    candidates = _prepare_candidates(
        providers=providers,
        impact=impact,
        scenario_id=scenario_id,
        clearing_method=clearing_method,
    )
    active_requirements = requirements.loc[
        requirements["required_kw"].astype(float) > 0.0
    ].sort_values(["timestep", "constraint_id"]).reset_index(drop=True)

    event_rows: list[dict[str, Any]] = []
    selection_rows: list[dict[str, Any]] = []

    for requirement in active_requirements.to_dict("records"):
        timestep = int(requirement["timestep"])
        constraint_id = str(requirement["constraint_id"])
        event_id = f"{scenario_id}:{constraint_id}:{timestep}"
        remaining_relief_kw = float(requirement["required_kw"])
        selected_soft_kw = 0.0
        selected_hard_kw = 0.0
        selected_relief_kw = 0.0
        estimated_cost = 0.0

        if candidates.empty:
            event_candidates = candidates
        else:
            event_candidates = candidates.loc[
                candidates["constraint_id"].astype(str) == constraint_id
            ].sort_values(
                [
                    "provider_priority",
                    "effective_cost_per_relief_kw_h",
                    "selection_priority",
                    "rank_score",
                    "provider_id",
                ],
                ascending=[True, True, True, False, True],
            )

        selected_count = 0
        for provider in event_candidates.to_dict("records"):
            if remaining_relief_kw <= 1e-9:
                break
            if selected_count >= max_selected_providers_per_event:
                break
            deliverability = float(provider["deliverability_factor"])
            capacity_kw = max(float(provider["available_capacity_kw"]), 0.0)
            selected_kw = min(capacity_kw, remaining_relief_kw / deliverability)
            expected_relief_kw = selected_kw * deliverability
            if selected_kw <= 0.0 or expected_relief_kw <= 0.0:
                continue

            provider_type = str(provider["provider_type"])
            if provider_type == "soft_cls_building":
                selected_soft_kw += selected_kw
            elif provider_type == "hard_cls_ev":
                selected_hard_kw += selected_kw
            selected_relief_kw += expected_relief_kw
            cost = selected_kw * float(provider["base_cost_per_kw_h"]) * float(dt_h)
            estimated_cost += cost
            selected_count += 1
            remaining_relief_kw = max(remaining_relief_kw - expected_relief_kw, 0.0)

            selection_rows.append(
                {
                    "event_id": event_id,
                    "scenario_id": scenario_id,
                    "timestep": timestep,
                    "timestamp": requirement.get("timestamp"),
                    "constraint_id": constraint_id,
                    "provider_id": provider["provider_id"],
                    "provider_type": provider_type,
                    "selected_kw": float(selected_kw),
                    "expected_relief_kw": float(expected_relief_kw),
                    "deliverability_factor": deliverability,
                    "rank_score": float(provider["rank_score"]),
                    "effective_cost_per_relief_kw_h": float(
                        provider["effective_cost_per_relief_kw_h"]
                    ),
                    "estimated_cost": float(cost),
                }
            )

        event_rows.append(
            {
                "event_id": event_id,
                "scenario_id": scenario_id,
                "timestep": timestep,
                "timestamp": requirement.get("timestamp"),
                "constraint_id": constraint_id,
                "required_kw": float(requirement["required_kw"]),
                "selected_relief_kw": float(selected_relief_kw),
                "selected_soft_kw": float(selected_soft_kw),
                "selected_hard_kw": float(selected_hard_kw),
                "shortfall_kw": float(max(remaining_relief_kw, 0.0)),
                "selected_provider_count": int(selected_count),
                "estimated_cost": float(estimated_cost),
                "overload_pctpt": float(requirement.get("overload_pctpt", 0.0) or 0.0),
                "clearing_method": clearing_method,
            }
        )

    events = pd.DataFrame(event_rows, columns=EVENT_COLUMNS)
    selections = pd.DataFrame(selection_rows, columns=SELECTION_COLUMNS)
    report = _build_report(
        events=events,
        selections=selections,
        scenario_id=scenario_id,
        clearing_method=clearing_method,
        dt_h=dt_h,
    )
    return events, selections, report


def _mwh(events: pd.DataFrame, column: str, dt_h: float) -> float:
    if events.empty or column not in events:
        return 0.0
    return float(events[column].astype(float).sum() * float(dt_h) / 1000.0)


def _constraint_summary(events: pd.DataFrame, selections: pd.DataFrame, dt_h: float) -> list[dict[str, Any]]:
    if events.empty:
        return []
    rows: list[dict[str, Any]] = []
    for constraint_id, group in events.groupby("constraint_id", sort=True):
        selected = (
            selections.loc[selections["constraint_id"].astype(str) == str(constraint_id)]
            if "constraint_id" in selections
            else pd.DataFrame(columns=SELECTION_COLUMNS)
        )
        rows.append(
            {
                "constraint_id": str(constraint_id),
                "event_count": int(len(group)),
                "required_mwh": _mwh(group, "required_kw", dt_h),
                "selected_relief_mwh": _mwh(group, "selected_relief_kw", dt_h),
                "shortfall_mwh": _mwh(group, "shortfall_kw", dt_h),
                "unique_provider_count": int(selected["provider_id"].nunique()) if not selected.empty else 0,
            }
        )
    return rows


def _provider_concentration_top10_pct(selections: pd.DataFrame) -> float | None:
    if selections.empty:
        return None
    by_provider = selections.groupby("provider_id")["expected_relief_kw"].sum().sort_values(
        ascending=False
    )
    total = float(by_provider.sum())
    if total <= 1e-12:
        return None
    return float(by_provider.head(10).sum() / total)


def _build_report(
    *,
    events: pd.DataFrame,
    selections: pd.DataFrame,
    scenario_id: str,
    clearing_method: str,
    dt_h: float,
) -> dict[str, Any]:
    required_mwh = _mwh(events, "required_kw", dt_h)
    selected_mwh = _mwh(events, "selected_relief_kw", dt_h)
    shortfall_mwh = _mwh(events, "shortfall_kw", dt_h)
    soft_selected_mwh = _mwh(events, "selected_soft_kw", dt_h)
    hard_selected_mwh = _mwh(events, "selected_hard_kw", dt_h)
    selected_provider_counts = (
        events["selected_provider_count"].astype(float) if not events.empty else pd.Series(dtype=float)
    )
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report_id": "locational_flexibility_clearing",
        "schema_version": "1.0",
        "scenario_id": scenario_id,
        "clearing_method": clearing_method,
        "clearing_policy": (
            "independent transformer constraint-event clearing; Soft CLS is "
            "preferred before Hard CLS and providers are ranked by local "
            "deliverability-adjusted offer cost"
        ),
        "dt_h": float(dt_h),
        "summary": {
            "constraint_event_count": int(len(events)),
            "constraint_count": int(events["constraint_id"].nunique()) if not events.empty else 0,
            "required_mwh": required_mwh,
            "selected_relief_mwh": selected_mwh,
            "shortfall_mwh": shortfall_mwh,
            "delivery_ratio": float(selected_mwh / required_mwh) if required_mwh > 1e-12 else None,
            "soft_selected_mwh": soft_selected_mwh,
            "hard_selected_mwh": hard_selected_mwh,
            "estimated_cost": float(events["estimated_cost"].sum()) if not events.empty else 0.0,
            "unique_provider_count": int(selections["provider_id"].nunique()) if not selections.empty else 0,
            "avg_selected_provider_count": float(selected_provider_counts.mean())
            if not selected_provider_counts.empty
            else 0.0,
            "provider_concentration_top10_pct": _provider_concentration_top10_pct(selections),
        },
        "constraint_summary": _constraint_summary(events, selections, dt_h),
    }


def write_locational_clearing_outputs(
    *,
    out_dir: Path,
    events: pd.DataFrame,
    selections: pd.DataFrame,
    report: dict[str, Any],
) -> dict[str, Path]:
    """Write locational clearing events, selections, and summary artifacts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    events_path = out_dir / "locational_clearing_events.parquet"
    selections_path = out_dir / "locational_clearing_selections.parquet"
    report_path = out_dir / "locational_clearing_summary.json"
    events.to_parquet(events_path, index=False)
    selections.to_parquet(selections_path, index=False)
    report_with_artifacts = {
        **report,
        "artifacts": {
            "events": events_path.name,
            "selections": selections_path.name,
            "summary": report_path.name,
        },
    }
    report_path.write_text(json.dumps(report_with_artifacts, indent=2, sort_keys=True, default=_json_default))
    return {
        "events": events_path,
        "selections": selections_path,
        "report": report_path,
    }
