"""Shadow comparison between aggregate CLS dispatch and local provider selection."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from gridalyn.operations.clearing.selection import select_providers_for_constraint


def _dispatch_dt_h(dispatch: pd.DataFrame) -> float:
    if "t_hours" in dispatch and len(dispatch) > 1:
        diffs = dispatch["t_hours"].diff().dropna()
        if not diffs.empty:
            return float(diffs.median())
    return 5.0 / 60.0


def _provider_selection_summary(selected: pd.DataFrame) -> tuple[float, float, list[dict[str, Any]]]:
    if selected.empty:
        return 0.0, 0.0, []
    by_type = selected.groupby("provider_type")["selected_kw"].sum()
    selected_soft_kw = float(by_type.get("soft_cls_building", 0.0))
    selected_hard_kw = float(by_type.get("hard_cls_ev", 0.0))
    selected_providers = []
    for row in selected.to_dict("records"):
        selected_providers.append(
            {
                "provider_id": row["provider_id"],
                "provider_type": row["provider_type"],
                "selected_kw": float(row["selected_kw"]),
                "expected_relief_kw": float(row["expected_relief_kw"]),
                "effective_cost_per_kw_h": float(row["effective_cost_per_kw_h"]),
            }
        )
    return selected_soft_kw, selected_hard_kw, selected_providers


def build_shadow_report(
    dispatch: pd.DataFrame,
    providers: pd.DataFrame,
    sensitivity: pd.DataFrame,
    *,
    scenario_id: str,
    constraint_ids: list[str],
    max_selected_providers_per_event: int = 20,
) -> dict[str, Any]:
    """Build a non-invasive report comparing aggregate dispatch to local selection."""
    dt_h = _dispatch_dt_h(dispatch)
    events: list[dict[str, Any]] = []
    scenario_providers = providers.loc[providers["scenario_id"] == scenario_id].copy()
    sensitivity_by_constraint = {
        constraint_id: sensitivity.loc[
            (sensitivity["scenario_id"] == scenario_id)
            & (sensitivity["constraint_id"] == constraint_id)
        ].copy()
        for constraint_id in constraint_ids
    }

    for _, row in dispatch.iterrows():
        aggregate_soft_kw = float(row.get("p_soft_cls_mw", 0.0) or 0.0) * 1000.0
        aggregate_hard_kw = float(row.get("p_hard_cls_mw", 0.0) or 0.0) * 1000.0
        required_kw = aggregate_soft_kw + aggregate_hard_kw
        if required_kw <= 0.0:
            continue

        for constraint_id in constraint_ids:
            selected = select_providers_for_constraint(
                scenario_providers,
                sensitivity_by_constraint[constraint_id],
                scenario_id=scenario_id,
                constraint_id=constraint_id,
                required_kw=required_kw,
            )
            selected_soft_kw, selected_hard_kw, selected_providers = _provider_selection_summary(
                selected.head(max_selected_providers_per_event)
            )
            selected_relief_kw = float(selected["expected_relief_kw"].sum()) if not selected.empty else 0.0
            local_shortfall_kw = max(0.0, required_kw - selected_relief_kw)
            total_cost = (
                float((selected["selected_kw"] * selected["effective_cost_per_kw_h"]).sum() * dt_h)
                if not selected.empty
                else 0.0
            )
            events.append(
                {
                    "t_hours": float(row.get("t_hours", 0.0) or 0.0),
                    "constraint_id": constraint_id,
                    "required_kw": required_kw,
                    "aggregate_soft_kw": aggregate_soft_kw,
                    "aggregate_hard_kw": aggregate_hard_kw,
                    "selected_soft_kw": selected_soft_kw,
                    "selected_hard_kw": selected_hard_kw,
                    "selected_relief_kw": selected_relief_kw,
                    "local_shortfall_kw": local_shortfall_kw,
                    "estimated_selection_cost": total_cost,
                    "selected_provider_count": int(len(selected)),
                    "selected_providers": selected_providers,
                }
            )

    aggregate_required_mwh = sum(event["required_kw"] * dt_h / 1000.0 for event in events)
    local_selected_mwh = sum(event["selected_relief_kw"] * dt_h / 1000.0 for event in events)
    local_shortfall_mwh = sum(event["local_shortfall_kw"] * dt_h / 1000.0 for event in events)
    unique_dispatch_required_mwh = float(
        (
            (dispatch.get("p_soft_cls_mw", 0.0) + dispatch.get("p_hard_cls_mw", 0.0))
            .clip(lower=0.0)
            .sum()
            * dt_h
        )
    )
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report_id": "provider_selection_shadow",
        "schema_version": "1.0",
        "scenario_id": scenario_id,
        "selection_method": "downstream_transformer_topology_effective_cost",
        "dt_h": dt_h,
        "constraint_ids": constraint_ids,
        "n_events": len(events),
        "summary": {
            "unique_dispatch_required_mwh": unique_dispatch_required_mwh,
            "aggregate_required_mwh": aggregate_required_mwh,
            "local_selected_mwh": local_selected_mwh,
            "local_shortfall_mwh": local_shortfall_mwh,
            "shortfall_event_count": int(sum(event["local_shortfall_kw"] > 0.0 for event in events)),
            "estimated_selection_cost": float(sum(event["estimated_selection_cost"] for event in events)),
        },
        "events": events,
    }


def write_shadow_report(path: Path, report: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(report, f, indent=2, sort_keys=True)
    return path
