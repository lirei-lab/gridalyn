"""Provider registry and first-pass network-aware flexibility selection."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd


SOFT_BASE_COST_PER_KW_H = 3.0
HARD_BASE_COST_PER_KW_H = 10.0


def _require_columns(df: pd.DataFrame, columns: list[str], label: str) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        raise ValueError(f"{label} is missing required columns: {', '.join(missing)}")


def _connectivity_lookup(connectivity: pd.DataFrame) -> pd.DataFrame:
    _require_columns(
        connectivity,
        ["building_id", "load_id", "load_bus_id", "lv_transformer_id"],
        "connectivity",
    )
    optional = [column for column in ["lv_feeder_bus_id", "lv_cluster"] if column in connectivity]
    return connectivity[["building_id", "load_id", "load_bus_id", "lv_transformer_id"] + optional]


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
        ["provider_id", "scenario_device_id", "device_id", "building_model_id", "device_type"],
        "scenario_device_registry",
    )
    lineage: dict[str, dict[str, Any]] = {}
    for provider_id, group in scenario_device_registry.groupby("provider_id", sort=False):
        scenario_device_ids = sorted(str(value) for value in group["scenario_device_id"].dropna().unique())
        device_ids = sorted(str(value) for value in group["device_id"].dropna().unique())
        device_types = sorted(str(value) for value in group["device_type"].dropna().unique())
        building_model_ids = [str(value) for value in group["building_model_id"].dropna().unique()]
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

        if bool(row.get("soft_cls_participant")) and float(row.get("max_soft_kw") or 0.0) > 0.0:
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
    return pd.DataFrame(rows, columns=columns).sort_values(
        ["scenario_id", "selection_priority", "provider_id"]
    ).reset_index(drop=True)


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
                    "available_relief_kw": float(provider["available_capacity_kw"]) * sensitivity,
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
        ["provider_id", "scenario_id", "available_capacity_kw", "base_cost_per_kw_h", "selection_priority"],
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
                "n_soft_building_providers": int((provider_type == "soft_cls_building").sum()),
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
