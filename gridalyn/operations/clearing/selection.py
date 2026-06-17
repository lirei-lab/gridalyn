"""Locational SELECTION clearing core.

This mode is the surrogate/locational selection path reached through the FROZEN
``run_flexibility_clearing_operation`` entry point. It bundles three formerly
separate modules unchanged in behavior:

* the frozen operational facade (``run_flexibility_clearing_operation``) from
  ``flexibility/clearing.py`` — its keyword-only signature and its delegation to
  ``build_locational_clearing`` are preserved verbatim (D-04);
* the locational clearing engine (``build_locational_clearing`` +
  ``build_constraint_requirements`` + ``write_locational_clearing_outputs``)
  from ``market/locational_clearing.py``;
* the provider registry / sensitivity helpers from ``market/providers.py``.

CLEAR-03 (determinism) is LOCKED here, not invented: the
``sort_values([..., "provider_id"])`` tie-breaks that already make the selection
order reproducible are moved verbatim. The lone ``set(...)`` over
``constraint_ids`` feeds an ``.isin(...)`` membership filter only (no ordering
leaks into output), so it is left as-is.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from gridalyn.operations.constraints import (
    build_network_constraint_set,
    summarize_network_constraints,
)
from gridalyn.operations.contracts import (
    build_operation_context,
    validate_flexibility_operation_inputs,
)
from gridalyn.operations.domain import (
    build_aggregator_portfolios,
    build_dispatch_instructions,
    build_settlement_records,
)
from gridalyn.operations.flexibility.kpis import build_operational_kpi_report


SOFT_BASE_COST_PER_KW_H = 3.0
HARD_BASE_COST_PER_KW_H = 10.0

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


def run_flexibility_clearing_operation(
    *,
    requirements: pd.DataFrame,
    providers: pd.DataFrame,
    impact: pd.DataFrame,
    scenario_id: str,
    dt_h: float,
    clearing_method: str = "surrogate",
    model_version_id: str | None = None,
    study_run_id: str | None = None,
    max_selected_providers_per_event: int = 1000,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Validate and execute a flexibility clearing operation."""
    context = build_operation_context(
        scenario_id=scenario_id,
        clearing_method=clearing_method,
        dt_h=dt_h,
        requirements=requirements,
        providers=providers,
        impact=impact,
        model_version_id=model_version_id,
        study_run_id=study_run_id,
    )
    validation = validate_flexibility_operation_inputs(
        requirements=requirements,
        providers=providers,
        impact=impact,
        context=context,
    )
    if not validation.valid:
        raise ValueError("; ".join(validation.errors))

    events, selections, report = build_locational_clearing(
        requirements=requirements,
        providers=providers,
        impact=impact,
        scenario_id=scenario_id,
        dt_h=dt_h,
        clearing_method=context.clearing_method,
        max_selected_providers_per_event=max_selected_providers_per_event,
    )
    report["operation_context"] = context.to_dict()
    report["governance"] = {
        "model_version_id": model_version_id,
        "study_run_id": study_run_id,
    }
    report["validation"] = validation.to_dict()
    report["input_summary"] = _input_summary(
        requirements=requirements,
        providers=providers,
        impact=impact,
        scenario_id=scenario_id,
    )
    dispatch = build_dispatch_instructions(
        selections=selections,
        providers=providers,
        context=context,
    )
    settlement = build_settlement_records(dispatch, dt_h=dt_h)
    portfolios = build_aggregator_portfolios(providers, scenario_id=scenario_id)
    constraints = build_network_constraint_set(
        requirements,
        scenario_id=scenario_id,
        model_version_id=model_version_id,
        study_run_id=study_run_id,
    )
    report["network_constraints"] = summarize_network_constraints(constraints)
    report["operation_domain"] = {
        "portfolio_count": int(len(portfolios)),
        "dispatch_instruction_count": int(len(dispatch)),
        "settlement_record_count": int(len(settlement)),
        "settlement_usd": float(settlement["payment_usd"].sum())
        if not settlement.empty
        else 0.0,
    }
    report["operational_kpis"] = build_operational_kpi_report(
        events=events,
        dispatch_instructions=dispatch,
        settlement_records=settlement,
        constraints=constraints,
        context=context,
        dt_h=dt_h,
    )
    return events, selections, report


def _input_summary(
    *,
    requirements: pd.DataFrame,
    providers: pd.DataFrame,
    impact: pd.DataFrame,
    scenario_id: str,
) -> dict[str, Any]:
    scenario_providers = providers.loc[
        providers["scenario_id"].astype(str) == str(scenario_id)
    ]
    aggregator_count = (
        int(scenario_providers["aggregator_id"].dropna().nunique())
        if "aggregator_id" in scenario_providers
        else 0
    )
    return {
        "requirement_count": int(len(requirements)),
        "provider_count": int(len(scenario_providers)),
        "impact_row_count": int(len(impact)),
        "constraint_count": int(requirements["constraint_id"].nunique())
        if "constraint_id" in requirements
        else 0,
        "aggregator_count": aggregator_count,
    }


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
    # NOTE (CLEAR-03 audit): this set feeds only the .isin(...) membership filter
    # below; iteration order over it never reaches any emitted output, so it is
    # deterministic-safe as-is and is deliberately left unsorted (lock, don't
    # invent — D-02).
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
        for index, timestamp in enumerate(
            frame["timestamp"].drop_duplicates().tolist()
        )
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
    scenario_providers = providers.loc[
        providers["scenario_id"].astype(str) == scenario_id
    ].copy()

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
        impact_frame = impact.loc[
            impact["scenario_id"].astype(str) == scenario_id
        ].copy()
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
        impact_frame = impact.loc[
            impact["scenario_id"].astype(str) == scenario_id
        ].copy()
        impact_frame["deliverability_factor"] = impact_frame[
            "sensitivity_kw_per_kw"
        ].astype(float)
        impact_frame["expected_capacity_relief_kw"] = impact_frame[
            "available_relief_kw"
        ].astype(float)
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
    candidates["provider_priority"] = candidates["provider_type"].map(
        _provider_priority
    )
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
    active_requirements = (
        requirements.loc[requirements["required_kw"].astype(float) > 0.0]
        .sort_values(["timestep", "constraint_id"])
        .reset_index(drop=True)
    )

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


def _constraint_summary(
    events: pd.DataFrame, selections: pd.DataFrame, dt_h: float
) -> list[dict[str, Any]]:
    if events.empty:
        return []
    rows: list[dict[str, Any]] = []
    for constraint_id, group in events.groupby("constraint_id", sort=True):
        selected = (
            selections.loc[
                selections["constraint_id"].astype(str) == str(constraint_id)
            ]
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
                "unique_provider_count": int(selected["provider_id"].nunique())
                if not selected.empty
                else 0,
            }
        )
    return rows


def _provider_concentration_top10_pct(selections: pd.DataFrame) -> float | None:
    if selections.empty:
        return None
    by_provider = (
        selections.groupby("provider_id")["expected_relief_kw"]
        .sum()
        .sort_values(ascending=False)
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
        events["selected_provider_count"].astype(float)
        if not events.empty
        else pd.Series(dtype=float)
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
            "constraint_count": int(events["constraint_id"].nunique())
            if not events.empty
            else 0,
            "required_mwh": required_mwh,
            "selected_relief_mwh": selected_mwh,
            "shortfall_mwh": shortfall_mwh,
            "delivery_ratio": float(selected_mwh / required_mwh)
            if required_mwh > 1e-12
            else None,
            "soft_selected_mwh": soft_selected_mwh,
            "hard_selected_mwh": hard_selected_mwh,
            "estimated_cost": float(events["estimated_cost"].sum())
            if not events.empty
            else 0.0,
            "unique_provider_count": int(selections["provider_id"].nunique())
            if not selections.empty
            else 0,
            "avg_selected_provider_count": float(selected_provider_counts.mean())
            if not selected_provider_counts.empty
            else 0.0,
            "provider_concentration_top10_pct": _provider_concentration_top10_pct(
                selections
            ),
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
    report_path.write_text(
        json.dumps(
            report_with_artifacts, indent=2, sort_keys=True, default=_json_default
        )
    )
    return {
        "events": events_path,
        "selections": selections_path,
        "report": report_path,
    }


def _connectivity_lookup(connectivity: pd.DataFrame) -> pd.DataFrame:
    _require_columns(
        connectivity,
        ["building_id", "load_id", "load_bus_id", "lv_transformer_id"],
        "connectivity",
    )
    optional = [
        column
        for column in ["lv_feeder_bus_id", "lv_cluster"]
        if column in connectivity
    ]
    return connectivity[
        ["building_id", "load_id", "load_bus_id", "lv_transformer_id"] + optional
    ]


def _provider_row(
    *,
    scenario_id: str,
    provider_type: str,
    provider_id: str,
    building_id: str,
    load_id: str,
    ev_id: str | None,
    pandapower_load: int | None,
    load_bus_id: str | None,
    feeder_bus_id: str | None,
    transformer_id: str | None,
    available_capacity_kw: float,
    base_cost_per_kw_h: float,
    priority: int,
    lineage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    lineage = lineage or {}
    return {
        "provider_id": provider_id,
        "scenario_id": scenario_id,
        "provider_type": provider_type,
        "building_id": building_id,
        "load_id": load_id,
        "ev_id": ev_id,
        "pandapower_load": pandapower_load,
        "load_bus_id": load_bus_id,
        "feeder_bus_id": feeder_bus_id,
        "constraint_zone_id": transformer_id,
        "constraint_zone_type": "cim:PowerTransformer" if transformer_id else None,
        "available_capacity_kw": float(max(0.0, available_capacity_kw)),
        "base_cost_per_kw_h": float(base_cost_per_kw_h),
        "selection_priority": int(priority),
        "source_standard": "EFOnt_CLS_CIM",
        "source_table": "asset_registry+building_grid_connectivity",
        "scenario_device_ids": lineage.get("scenario_device_ids"),
        "device_ids": lineage.get("device_ids"),
        "building_model_id": lineage.get("building_model_id"),
        "device_types": lineage.get("device_types"),
        "aggregator_id": lineage.get("aggregator_id"),
        "scenario_device_count": int(lineage.get("scenario_device_count") or 0),
    }


def _scenario_device_lineage(
    scenario_device_registry: pd.DataFrame | None,
) -> dict[str, dict[str, Any]]:
    if scenario_device_registry is None or scenario_device_registry.empty:
        return {}
    _require_columns(
        scenario_device_registry,
        [
            "provider_id",
            "scenario_device_id",
            "device_id",
            "building_model_id",
            "device_type",
        ],
        "scenario_device_registry",
    )
    lineage: dict[str, dict[str, Any]] = {}
    for provider_id, group in scenario_device_registry.groupby(
        "provider_id", sort=False
    ):
        scenario_device_ids = sorted(
            str(value) for value in group["scenario_device_id"].dropna().unique()
        )
        device_ids = sorted(
            str(value) for value in group["device_id"].dropna().unique()
        )
        device_types = sorted(
            str(value) for value in group["device_type"].dropna().unique()
        )
        building_model_ids = [
            str(value) for value in group["building_model_id"].dropna().unique()
        ]
        aggregator_ids = (
            [str(value) for value in group["aggregator_id"].dropna().unique()]
            if "aggregator_id" in group.columns
            else []
        )
        lineage[str(provider_id)] = {
            "scenario_device_ids": ";".join(scenario_device_ids) or None,
            "device_ids": ";".join(device_ids) or None,
            "building_model_id": building_model_ids[0] if building_model_ids else None,
            "device_types": ";".join(device_types) or None,
            "aggregator_id": aggregator_ids[0] if aggregator_ids else None,
            "scenario_device_count": len(scenario_device_ids),
        }
    return lineage


def build_provider_registry(
    asset_registry: pd.DataFrame,
    connectivity: pd.DataFrame,
    scenario_device_registry: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build one row per controllable Soft CLS building and Hard CLS EV provider."""
    _require_columns(
        asset_registry,
        [
            "scenario_id",
            "building_id",
            "load_id",
            "soft_cls_participant",
            "hard_cls_enabled",
            "has_ev",
            "max_soft_kw",
            "max_hard_kw",
        ],
        "asset_registry",
    )
    connectivity_key = _connectivity_lookup(connectivity)
    merged = asset_registry.merge(
        connectivity_key,
        on=["building_id", "load_id"],
        how="left",
        validate="many_to_one",
        suffixes=("", "_connectivity"),
    )

    lineage_by_provider = _scenario_device_lineage(scenario_device_registry)
    rows: list[dict[str, Any]] = []
    for row in merged.to_dict("records"):
        scenario_id = str(row["scenario_id"])
        building_id = str(row["building_id"])
        load_id = str(row["load_id"])
        transformer_id = row.get("lv_transformer_id")
        load_bus_id = row.get("load_bus_id") or row.get("lv_bus_id")
        feeder_bus_id = row.get("lv_feeder_bus_id")
        pandapower_load = row.get("pandapower_load")

        if (
            bool(row.get("soft_cls_participant"))
            and float(row.get("max_soft_kw") or 0.0) > 0.0
        ):
            provider_id = f"provider:{scenario_id}:{building_id}:soft_cls"
            rows.append(
                _provider_row(
                    scenario_id=scenario_id,
                    provider_type="soft_cls_building",
                    provider_id=provider_id,
                    building_id=building_id,
                    load_id=load_id,
                    ev_id=None,
                    pandapower_load=pandapower_load,
                    load_bus_id=load_bus_id,
                    feeder_bus_id=feeder_bus_id,
                    transformer_id=transformer_id,
                    available_capacity_kw=float(row.get("max_soft_kw") or 0.0),
                    base_cost_per_kw_h=SOFT_BASE_COST_PER_KW_H,
                    priority=1,
                    lineage=lineage_by_provider.get(provider_id),
                )
            )

        if (
            bool(row.get("has_ev"))
            and bool(row.get("hard_cls_enabled"))
            and float(row.get("max_hard_kw") or 0.0) > 0.0
        ):
            ev_id = str(row.get("ev_id"))
            provider_id = f"provider:{scenario_id}:{ev_id}:hard_cls"
            rows.append(
                _provider_row(
                    scenario_id=scenario_id,
                    provider_type="hard_cls_ev",
                    provider_id=provider_id,
                    building_id=building_id,
                    load_id=load_id,
                    ev_id=ev_id,
                    pandapower_load=pandapower_load,
                    load_bus_id=load_bus_id,
                    feeder_bus_id=feeder_bus_id,
                    transformer_id=transformer_id,
                    available_capacity_kw=float(row.get("max_hard_kw") or 0.0),
                    base_cost_per_kw_h=HARD_BASE_COST_PER_KW_H,
                    priority=2,
                    lineage=lineage_by_provider.get(provider_id),
                )
            )

    columns = [
        "provider_id",
        "scenario_id",
        "provider_type",
        "building_id",
        "load_id",
        "ev_id",
        "pandapower_load",
        "load_bus_id",
        "feeder_bus_id",
        "constraint_zone_id",
        "constraint_zone_type",
        "available_capacity_kw",
        "base_cost_per_kw_h",
        "selection_priority",
        "source_standard",
        "source_table",
        "scenario_device_ids",
        "device_ids",
        "building_model_id",
        "device_types",
        "aggregator_id",
        "scenario_device_count",
    ]
    return (
        pd.DataFrame(rows, columns=columns)
        .sort_values(["scenario_id", "selection_priority", "provider_id"])
        .reset_index(drop=True)
    )


def build_network_sensitivity(providers: pd.DataFrame) -> pd.DataFrame:
    """Build a topology-based provider-to-transformer sensitivity table."""
    _require_columns(
        providers,
        ["provider_id", "scenario_id", "constraint_zone_id", "available_capacity_kw"],
        "providers",
    )
    constraints = sorted(
        str(value)
        for value in providers["constraint_zone_id"].dropna().unique()
        if str(value)
    )
    rows: list[dict[str, Any]] = []
    for provider in providers.to_dict("records"):
        provider_zone = provider.get("constraint_zone_id")
        for constraint_id in constraints:
            sensitivity = 1.0 if provider_zone == constraint_id else 0.0
            rows.append(
                {
                    "provider_id": provider["provider_id"],
                    "scenario_id": provider["scenario_id"],
                    "constraint_id": constraint_id,
                    "constraint_type": "cim:PowerTransformer",
                    "sensitivity_kw_per_kw": sensitivity,
                    "deliverability_factor": sensitivity,
                    "method": "downstream_transformer_topology",
                    "available_relief_kw": float(provider["available_capacity_kw"])
                    * sensitivity,
                }
            )
    return pd.DataFrame(rows)


def select_providers_for_constraint(
    providers: pd.DataFrame,
    sensitivity: pd.DataFrame,
    *,
    scenario_id: str,
    constraint_id: str,
    required_kw: float,
) -> pd.DataFrame:
    """Select local providers by effective cost until required relief is covered."""
    if required_kw <= 0:
        return pd.DataFrame()
    _require_columns(
        providers,
        [
            "provider_id",
            "scenario_id",
            "available_capacity_kw",
            "base_cost_per_kw_h",
            "selection_priority",
        ],
        "providers",
    )
    _require_columns(
        sensitivity,
        ["provider_id", "scenario_id", "constraint_id", "sensitivity_kw_per_kw"],
        "sensitivity",
    )

    candidates = providers.merge(
        sensitivity,
        on=["provider_id", "scenario_id"],
        how="inner",
        validate="one_to_many",
    )
    candidates = candidates.loc[
        (candidates["scenario_id"] == scenario_id)
        & (candidates["constraint_id"] == constraint_id)
        & (candidates["sensitivity_kw_per_kw"] > 0.0)
    ].copy()
    if candidates.empty:
        return candidates

    candidates["effective_cost_per_kw_h"] = (
        candidates["base_cost_per_kw_h"] / candidates["sensitivity_kw_per_kw"]
    )
    candidates = candidates.sort_values(
        ["effective_cost_per_kw_h", "selection_priority", "provider_id"]
    ).reset_index(drop=True)

    remaining = float(required_kw)
    selected_rows: list[dict[str, Any]] = []
    for row in candidates.to_dict("records"):
        selected_kw = min(float(row["available_capacity_kw"]), remaining)
        if selected_kw <= 0:
            continue
        row["selected_kw"] = selected_kw
        row["expected_relief_kw"] = selected_kw * float(row["sensitivity_kw_per_kw"])
        selected_rows.append(row)
        remaining -= row["expected_relief_kw"]
        if remaining <= 1e-9:
            break
    return pd.DataFrame(selected_rows)


def summarize_provider_registry(providers: pd.DataFrame) -> dict[str, Any]:
    """Summarize provider counts and available capacity by scenario."""
    _require_columns(
        providers,
        ["scenario_id", "provider_type", "available_capacity_kw"],
        "providers",
    )
    scenarios = []
    for scenario_id, group in providers.groupby("scenario_id", sort=True):
        provider_type = group["provider_type"]
        scenarios.append(
            {
                "scenario_id": str(scenario_id),
                "n_providers": int(len(group)),
                "n_soft_building_providers": int(
                    (provider_type == "soft_cls_building").sum()
                ),
                "n_hard_ev_providers": int((provider_type == "hard_cls_ev").sum()),
                "available_capacity_kw": float(group["available_capacity_kw"].sum()),
                "n_constraint_zones": int(group["constraint_zone_id"].nunique()),
            }
        )

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider_registry_version": 1,
        "selection_method": "downstream_transformer_topology_effective_cost",
        "scenarios": scenarios,
    }
