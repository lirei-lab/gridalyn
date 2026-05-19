"""Scenario overlays for building model devices."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


SCENARIO_SOURCE_STANDARD = "pycity-inspired-scenario-overlay"
ASSET_REGISTRY_SOURCE_TABLE = "instances/default/digital_twin/scenarios/asset_registry.parquet"


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, float) and math.isnan(value):
        return False
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y"}


def _float_value(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(result):
        return default
    return result


def _text_or_none(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value)
    return text if text and text.lower() != "nan" else None


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _scenario_ids(asset_registry: pd.DataFrame, scenario_id: str | None) -> list[str]:
    if "scenario_id" not in asset_registry.columns:
        raise ValueError("asset_registry must include scenario_id")
    if scenario_id:
        return [scenario_id]
    return sorted(str(value) for value in asset_registry["scenario_id"].dropna().unique())


def _base_hvac_devices(base_device_registry: pd.DataFrame) -> pd.DataFrame:
    if "device_type" not in base_device_registry.columns:
        raise ValueError("base_device_registry must include device_type")
    return base_device_registry[
        base_device_registry["device_type"].isin(["hvac_heating", "hvac_cooling"])
    ].copy()


def _soft_device_records(
    *,
    scenario_id: str,
    asset_row: dict[str, object],
    building_devices: pd.DataFrame,
    building_model: dict[str, object],
) -> list[dict[str, object]]:
    if building_devices.empty:
        return []
    max_soft_kw = _float_value(asset_row.get("max_soft_kw"))
    total_rated_kw = max(float(building_devices["rated_power_kw"].sum()), 0.0)
    aggregator_id = _text_or_none(asset_row.get("aggregator_id")) or f"aggregator:{scenario_id}:default"
    provider_id = f"provider:{scenario_id}:{asset_row['building_id']}:soft_cls"

    records: list[dict[str, object]] = []
    for device in building_devices.to_dict("records"):
        rated_power_kw = _float_value(device.get("rated_power_kw"))
        if max_soft_kw > 0 and total_rated_kw > 0:
            available_kw = min(rated_power_kw, max_soft_kw * rated_power_kw / total_rated_kw)
        else:
            available_kw = rated_power_kw
        records.append(
            {
                "scenario_id": scenario_id,
                "scenario_device_id": f"scenario_device:{scenario_id}:{device['device_id']}",
                "device_id": str(device["device_id"]),
                "building_model_id": str(device["building_model_id"]),
                "building_id": str(device["building_id"]),
                "load_id": _text_or_none(building_model.get("load_id")),
                "load_bus_id": _text_or_none(building_model.get("load_bus_id")),
                "constraint_zone_id": _text_or_none(building_model.get("lv_transformer_id")),
                "lv_transformer_id": _text_or_none(building_model.get("lv_transformer_id")),
                "device_type": str(device["device_type"]),
                "rated_power_kw": round(rated_power_kw, 6),
                "available_kw": round(float(available_kw), 6),
                "controllable": bool(device.get("controllable", True)),
                "contract_role": "soft_cls_provider",
                "contract_type": _text_or_none(asset_row.get("contract_type")) or "soft_building",
                "aggregator_id": aggregator_id,
                "provider_id": provider_id,
                "ev_id": None,
                "source_standard": SCENARIO_SOURCE_STANDARD,
                "source_table": ASSET_REGISTRY_SOURCE_TABLE,
            }
        )
    return records


def _evse_device_record(
    *,
    scenario_id: str,
    asset_row: dict[str, object],
    building_model: dict[str, object],
) -> dict[str, object] | None:
    ev_id = _text_or_none(asset_row.get("ev_id"))
    if not ev_id:
        return None
    building_id = str(asset_row["building_id"])
    rated_power_kw = _float_value(asset_row.get("charger_kw"))
    available_kw = _float_value(asset_row.get("max_hard_kw"), rated_power_kw) or rated_power_kw
    device_id = f"device:{building_id}:evse_l2"
    aggregator_id = _text_or_none(asset_row.get("aggregator_id")) or f"aggregator:{scenario_id}:default"
    return {
        "scenario_id": scenario_id,
        "scenario_device_id": f"scenario_device:{scenario_id}:{device_id}",
        "device_id": device_id,
        "building_model_id": str(building_model["model_id"]),
        "building_id": building_id,
        "load_id": _text_or_none(building_model.get("load_id")),
        "load_bus_id": _text_or_none(building_model.get("load_bus_id")),
        "constraint_zone_id": _text_or_none(building_model.get("lv_transformer_id")),
        "lv_transformer_id": _text_or_none(building_model.get("lv_transformer_id")),
        "device_type": "evse_l2",
        "rated_power_kw": round(rated_power_kw, 6),
        "available_kw": round(available_kw, 6),
        "controllable": True,
        "contract_role": "hard_cls_backstop",
        "contract_type": _text_or_none(asset_row.get("contract_type")) or "hard_ev",
        "aggregator_id": aggregator_id,
        "provider_id": f"provider:{scenario_id}:{ev_id}:hard_cls",
        "ev_id": ev_id,
        "source_standard": SCENARIO_SOURCE_STANDARD,
        "source_table": ASSET_REGISTRY_SOURCE_TABLE,
    }


def synthesize_scenario_device_tables(
    building_models: pd.DataFrame,
    base_device_registry: pd.DataFrame,
    asset_registry: pd.DataFrame,
    *,
    scenario_id: str | None = None,
) -> dict[str, pd.DataFrame]:
    """Create scenario-specific device overlays from model and asset tables."""

    for column in ["building_id", "model_id"]:
        if column not in building_models.columns:
            raise ValueError(f"building_models must include {column}")
    for column in ["scenario_id", "building_id"]:
        if column not in asset_registry.columns:
            raise ValueError(f"asset_registry must include {column}")

    models_by_building = {
        str(row["building_id"]): row for row in building_models.to_dict("records")
    }
    hvac_devices = _base_hvac_devices(base_device_registry)
    devices_by_building = {
        str(building_id): group
        for building_id, group in hvac_devices.groupby("building_id", sort=False)
    }

    device_records: list[dict[str, object]] = []
    summary_records: list[dict[str, object]] = []
    for sid in _scenario_ids(asset_registry, scenario_id):
        scenario_assets = asset_registry[asset_registry["scenario_id"].astype(str) == sid]
        for asset_row in scenario_assets.to_dict("records"):
            building_id = str(asset_row["building_id"])
            building_model = models_by_building.get(building_id)
            if not building_model:
                continue
            if _bool_value(asset_row.get("soft_cls_participant")):
                device_records.extend(
                    _soft_device_records(
                        scenario_id=sid,
                        asset_row=asset_row,
                        building_devices=devices_by_building.get(building_id, pd.DataFrame()),
                        building_model=building_model,
                    )
                )
            if _bool_value(asset_row.get("hard_cls_enabled")) and _bool_value(asset_row.get("has_ev")):
                evse_record = _evse_device_record(
                    scenario_id=sid,
                    asset_row=asset_row,
                    building_model=building_model,
                )
                if evse_record:
                    device_records.append(evse_record)

        scenario_devices = [record for record in device_records if record["scenario_id"] == sid]
        summary_records.append(
            {
                "scenario_id": sid,
                "scenario_devices": len(scenario_devices),
                "ev_buildings": int(scenario_assets["has_ev"].map(_bool_value).sum())
                if "has_ev" in scenario_assets.columns
                else 0,
                "soft_cls_buildings": int(scenario_assets["soft_cls_participant"].map(_bool_value).sum())
                if "soft_cls_participant" in scenario_assets.columns
                else 0,
                "hard_cls_evs": int(scenario_assets["hard_cls_enabled"].map(_bool_value).sum())
                if "hard_cls_enabled" in scenario_assets.columns
                else 0,
                "hard_only_evs": int((scenario_assets["contract_type"].astype(str) == "hard_ev").sum())
                if "contract_type" in scenario_assets.columns
                else 0,
                "soft_hard_overlap": int((scenario_assets["contract_type"].astype(str) == "soft+hard_ev").sum())
                if "contract_type" in scenario_assets.columns
                else 0,
                "evse_devices": sum(1 for record in scenario_devices if record["device_type"] == "evse_l2"),
                "soft_device_rows": sum(
                    1 for record in scenario_devices if record["contract_role"] == "soft_cls_provider"
                ),
                "hard_device_rows": sum(
                    1 for record in scenario_devices if record["contract_role"] == "hard_cls_backstop"
                ),
                "available_soft_kw": round(
                    sum(
                        float(record["available_kw"])
                        for record in scenario_devices
                        if record["contract_role"] == "soft_cls_provider"
                    ),
                    6,
                ),
                "available_hard_kw": round(
                    sum(
                        float(record["available_kw"])
                        for record in scenario_devices
                        if record["contract_role"] == "hard_cls_backstop"
                    ),
                    6,
                ),
            }
        )

    return {
        "scenario_device_registry": pd.DataFrame.from_records(device_records),
        "scenario_summary": pd.DataFrame.from_records(summary_records),
    }


def write_scenario_model_artifacts(
    building_models: pd.DataFrame,
    base_device_registry: pd.DataFrame,
    asset_registry: pd.DataFrame,
    *,
    out_dir: Path = Path("instances/default/digital_twin/models/scenarios"),
    root: Path = Path("."),
    scenario_id: str | None = None,
) -> dict[str, Any]:
    """Write scenario model overlay Parquet files and manifest."""

    out_dir.mkdir(parents=True, exist_ok=True)
    tables = synthesize_scenario_device_tables(
        building_models,
        base_device_registry,
        asset_registry,
        scenario_id=scenario_id,
    )
    devices = tables["scenario_device_registry"]
    summary = tables["scenario_summary"]

    artifacts: dict[str, str] = {}
    for sid in sorted(summary["scenario_id"].astype(str).tolist()):
        scenario_devices = devices[devices["scenario_id"].astype(str) == sid]
        path = out_dir / f"{sid}_device_registry.parquet"
        scenario_devices.to_parquet(path, index=False)
        artifacts[f"{sid}_device_registry"] = _relative(path, root)

    summary_path = out_dir / "scenario_summary.parquet"
    summary.to_parquet(summary_path, index=False)
    artifacts["scenario_summary"] = _relative(summary_path, root)

    integer_count_keys = {
        "scenario_devices",
        "ev_buildings",
        "soft_cls_buildings",
        "hard_cls_evs",
        "hard_only_evs",
        "soft_hard_overlap",
        "evse_devices",
        "soft_device_rows",
        "hard_device_rows",
    }
    scenario_counts = {
        str(row["scenario_id"]): {
            key: int(row[key]) if key in integer_count_keys else float(row[key])
            for key in [
                "scenario_devices",
                "ev_buildings",
                "soft_cls_buildings",
                "hard_cls_evs",
                "hard_only_evs",
                "soft_hard_overlap",
                "evse_devices",
                "soft_device_rows",
                "hard_device_rows",
                "available_soft_kw",
                "available_hard_kw",
            ]
        }
        for row in summary.to_dict("records")
    }
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "report_id": "scenario_model_manifest",
        "schema_version": "1.0",
        "source_standard": SCENARIO_SOURCE_STANDARD,
        "counts": {
            "scenarios": int(len(summary)),
            "scenario_devices": int(len(devices)),
        },
        "scenario_counts": scenario_counts,
        "inputs": {
            "building_models": "instances/default/digital_twin/models/building_models.parquet",
            "base_device_registry": "instances/default/digital_twin/models/device_registry.parquet",
            "asset_registry": ASSET_REGISTRY_SOURCE_TABLE,
        },
        "artifacts": artifacts,
        "root": ".",
    }
    manifest_path = out_dir / "scenario_model_manifest.json"
    manifest["manifest_path"] = _relative(manifest_path, root)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest
