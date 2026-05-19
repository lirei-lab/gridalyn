"""Scenario-level asset registry helpers for the digital twin."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd


BUILDING_KEY = ["building_id", "load_id", "pandapower_load"]


def _require_columns(df: pd.DataFrame, columns: list[str], label: str) -> None:
    missing = [column for column in columns if column not in df.columns]
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"{label} is missing required columns: {joined}")


def _soft_participant_mask(
    buildings: pd.DataFrame,
    participation_rate: float,
    seed: int,
    prefer_existing: bool,
) -> tuple[np.ndarray, str]:
    if "cls_participant" in buildings and prefer_existing:
        existing = buildings["cls_participant"].fillna(False).to_numpy(dtype=bool)
        if existing.any():
            return existing, "digital_twin_base_cls_participant"

    if not 0.0 <= participation_rate <= 1.0:
        raise ValueError("soft_participation_rate must be between 0 and 1")

    n_buildings = len(buildings)
    n_selected = int(round(n_buildings * participation_rate))
    mask = np.zeros(n_buildings, dtype=bool)
    if n_selected > 0:
        rng = np.random.default_rng(seed)
        mask[rng.permutation(n_buildings)[:n_selected]] = True
    return mask, "seeded_random_building_participation"


def _contract_type(soft: bool, hard: bool) -> str:
    if soft and hard:
        return "soft+hard_ev"
    if soft:
        return "soft_building"
    if hard:
        return "hard_ev"
    return "none"


def build_asset_registry(
    buildings: pd.DataFrame,
    assignments: pd.DataFrame,
    *,
    soft_participation_rate: float,
    soft_assignment_seed: int,
    default_soft_capacity_fraction: float = 0.65,
    prefer_existing_soft_participants: bool = False,
) -> pd.DataFrame:
    """Build one row per scenario/building with EV and CLS contract roles."""
    _require_columns(buildings, BUILDING_KEY, "buildings")
    _require_columns(
        assignments,
        BUILDING_KEY
        + ["scenario_id", "has_ev", "ev_id", "charger_kw", "c_soft_fraction"],
        "assignments",
    )

    stable_buildings = (
        buildings.copy()
        .sort_values("pandapower_load")
        .reset_index(drop=True)
    )
    soft_mask, soft_policy = _soft_participant_mask(
        stable_buildings,
        soft_participation_rate,
        soft_assignment_seed,
        prefer_existing_soft_participants,
    )

    optional_building_cols = [
        "lv_bus_id",
        "lat",
        "lon",
        "area_m2",
        "static_p_mw",
    ]
    building_cols = BUILDING_KEY + [
        column for column in optional_building_cols if column in stable_buildings.columns
    ]
    building_assets = stable_buildings[building_cols].copy()
    building_assets["soft_cls_participant"] = soft_mask
    building_assets["soft_participation_rate"] = float(soft_participation_rate)
    building_assets["soft_assignment_seed"] = int(soft_assignment_seed)
    building_assets["soft_assignment_policy"] = soft_policy

    registry = assignments.copy().merge(
        building_assets,
        on=BUILDING_KEY,
        how="left",
        validate="many_to_one",
    )
    if registry["soft_cls_participant"].isna().any():
        raise ValueError("assignments contain buildings that are not present in base buildings")

    registry["has_ev"] = registry["has_ev"].fillna(False).astype(bool)
    registry["soft_cls_participant"] = registry["soft_cls_participant"].astype(bool)
    registry["hard_cls_enabled"] = registry["has_ev"]
    registry["ev_count"] = registry["has_ev"].astype(int)
    registry["charger_kw"] = registry["charger_kw"].fillna(0.0).astype(float)
    registry["c_soft_fraction"] = registry["c_soft_fraction"].fillna(0.0).astype(float)

    if "static_p_mw" in registry.columns:
        static_kw = registry["static_p_mw"].fillna(0.0).astype(float) * 1000.0
    else:
        static_kw = pd.Series(np.zeros(len(registry)), index=registry.index)
    soft_fraction = registry["c_soft_fraction"].where(
        registry["c_soft_fraction"] > 0.0,
        float(default_soft_capacity_fraction),
    )
    registry["max_soft_kw"] = np.where(
        registry["soft_cls_participant"],
        static_kw * soft_fraction,
        0.0,
    )
    registry["max_hard_kw"] = np.where(
        registry["hard_cls_enabled"],
        registry["charger_kw"],
        0.0,
    )
    registry["contract_type"] = [
        _contract_type(soft, hard)
        for soft, hard in zip(
            registry["soft_cls_participant"],
            registry["hard_cls_enabled"],
            strict=True,
        )
    ]
    registry["asset_registry_version"] = 1

    first_cols = [
        "scenario_id",
        "building_id",
        "load_id",
        "pandapower_load",
        "lv_bus_id",
        "lat",
        "lon",
        "area_m2",
        "has_ev",
        "ev_id",
        "ev_count",
        "charger_kw",
        "soft_cls_participant",
        "hard_cls_enabled",
        "contract_type",
        "max_soft_kw",
        "max_hard_kw",
        "c_soft_fraction",
        "soft_participation_rate",
        "soft_assignment_seed",
        "soft_assignment_policy",
        "asset_registry_version",
    ]
    ordered = [column for column in first_cols if column in registry.columns]
    remaining = [column for column in registry.columns if column not in ordered]
    return registry[ordered + remaining].sort_values(
        ["scenario_id", "pandapower_load"]
    ).reset_index(drop=True)


def summarize_asset_registry(registry: pd.DataFrame) -> dict[str, Any]:
    """Summarize registry participation and EV/CLS overlap by scenario."""
    _require_columns(
        registry,
        [
            "scenario_id",
            "has_ev",
            "soft_cls_participant",
            "hard_cls_enabled",
            "max_soft_kw",
            "max_hard_kw",
        ],
        "registry",
    )

    scenarios = []
    for scenario_id, group in registry.groupby("scenario_id", sort=True):
        has_ev = group["has_ev"].astype(bool)
        soft = group["soft_cls_participant"].astype(bool)
        hard = group["hard_cls_enabled"].astype(bool)
        scenarios.append(
            {
                "scenario_id": str(scenario_id),
                "n_buildings": int(len(group)),
                "n_ev": int(has_ev.sum()),
                "n_soft_participants": int(soft.sum()),
                "n_hard_cls_enabled": int(hard.sum()),
                "n_soft_and_ev": int((soft & has_ev).sum()),
                "n_hard_preferred": int((hard & ~soft).sum()),
                "max_soft_kw": float(group["max_soft_kw"].sum()),
                "max_hard_kw": float(group["max_hard_kw"].sum()),
            }
        )

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "asset_registry_version": 1,
        "n_scenarios": int(len(scenarios)),
        "scenarios": scenarios,
    }
