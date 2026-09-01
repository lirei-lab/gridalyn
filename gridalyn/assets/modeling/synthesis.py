"""Synthesize pyCity-style building model tables from digital-twin assets."""

from __future__ import annotations

import math
from collections.abc import Mapping

import pandas as pd

from gridalyn.assets.modeling.archetypes import (
    NORTH_AMERICA_RESIDENTIAL_PROFILE,
    select_archetype,
)
from gridalyn.assets.modeling.buildings import BuildingModel, EndUseLoad, ThermalZone
from gridalyn.assets.modeling.devices import (
    evse_device_for_building,
    hvac_devices_for_building,
)

SOURCE_STANDARD = "pycity-inspired"
BUILDINGS_SOURCE_TABLE = "instances/default/digital_twin/base/buildings.parquet"


def _none_if_missing(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value)
    return text if text and text.lower() != "nan" else None


def _bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, float) and math.isnan(value):
        return False
    return str(value).strip().lower() in {"1", "true", "t", "yes", "y"}


def _float_value(value: object, default: float) -> float:
    if value is None:
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(result):
        return default
    return result


def _stable_multiplier(row: Mapping[str, object], column: str, spread: float) -> float:
    seed = int(_float_value(row.get(column), 0.0))
    bucket = (seed % 17) - 8
    return 1.0 + bucket * spread / 8.0


def _dwelling_units(area_m2: float, default_units: int) -> int:
    if area_m2 < 300.0:
        return default_units
    return max(default_units, int(round(area_m2 / 95.0)))


def _merge_connectivity(
    buildings: pd.DataFrame, connectivity: pd.DataFrame | None
) -> pd.DataFrame:
    if connectivity is None or connectivity.empty:
        return buildings.copy()
    keep = [
        column
        for column in [
            "building_id",
            "load_bus_id",
            "lv_cluster",
            "lv_feeder_bus_id",
            "lv_transformer_id",
            "connectivity_status",
        ]
        if column in connectivity.columns
    ]
    if "building_id" not in keep:
        return buildings.copy()
    return buildings.merge(
        connectivity[keep], on="building_id", how="left", suffixes=("", "_connectivity")
    )


def synthesize_building_model_tables(
    buildings: pd.DataFrame,
    connectivity: pd.DataFrame | None = None,
    *,
    profile: str = NORTH_AMERICA_RESIDENTIAL_PROFILE,
    include_evse: bool = True,
) -> dict[str, pd.DataFrame]:
    """Create normalized building, zone, device, and end-use tables."""

    if "building_id" not in buildings.columns:
        raise ValueError("buildings must include a building_id column")

    merged = _merge_connectivity(buildings, connectivity)
    building_records: list[dict[str, object]] = []
    zone_records: list[dict[str, object]] = []
    device_records: list[dict[str, object]] = []
    end_use_records: list[dict[str, object]] = []

    for raw in merged.sort_values("building_id").to_dict("records"):
        building_id = str(raw["building_id"])
        model_id = f"building_model:{building_id}"
        area_m2 = max(_float_value(raw.get("area_m2"), 100.0), 1.0)
        static_p_kw = max(_float_value(raw.get("static_p_mw"), 0.0) * 1000.0, 0.0)
        archetype = select_archetype(area_m2, profile=profile)
        dwelling_units = _dwelling_units(area_m2, archetype.dwelling_units)

        heating_capacity_kw = max(
            archetype.heating_kw_per_m2
            * area_m2
            * _stable_multiplier(raw, "thermal_seed_base", 0.08),
            static_p_kw * 0.35,
            0.5,
        )
        cooling_capacity_kw = max(
            archetype.cooling_kw_per_m2
            * area_m2
            * _stable_multiplier(raw, "load_seed_base", 0.06),
            0.25,
        )
        base_load_kw = max(
            archetype.base_load_kw_per_m2
            * area_m2
            * _stable_multiplier(raw, "load_seed_base", 0.05),
            static_p_kw * 0.2,
            0.05,
        )
        thermal_resistance = archetype.thermal_resistance_c_per_kw * _stable_multiplier(
            raw,
            "thermal_seed_base",
            0.05,
        )
        thermal_capacitance = archetype.thermal_capacitance_kwh_per_c * area_m2 / 100.0

        load_bus_id = _none_if_missing(raw.get("load_bus_id")) or _none_if_missing(
            raw.get("lv_bus_id")
        )
        has_ev = _bool_value(raw.get("has_ev"))
        ev_id = _none_if_missing(raw.get("ev_id"))

        model = BuildingModel(
            model_id=model_id,
            building_id=building_id,
            load_id=_none_if_missing(raw.get("load_id")),
            load_bus_id=load_bus_id,
            lv_bus_id=_none_if_missing(raw.get("lv_bus_id")),
            lv_transformer_id=_none_if_missing(raw.get("lv_transformer_id")),
            lv_feeder_bus_id=_none_if_missing(raw.get("lv_feeder_bus_id")),
            lv_cluster=_none_if_missing(raw.get("lv_cluster")),
            archetype_id=archetype.archetype_id,
            model_profile=profile,
            source_standard=SOURCE_STANDARD,
            source_table=BUILDINGS_SOURCE_TABLE,
            source_id=building_id,
            floor_area_m2=round(area_m2, 6),
            dwelling_units=dwelling_units,
            static_p_kw=round(static_p_kw, 6),
            base_load_kw=round(base_load_kw, 6),
            heating_capacity_kw=round(heating_capacity_kw, 6),
            cooling_capacity_kw=round(cooling_capacity_kw, 6),
            thermal_resistance_c_per_kw=round(thermal_resistance, 6),
            thermal_capacitance_kwh_per_c=round(thermal_capacitance, 6),
            flexibility_class=archetype.flexibility_class,
            scenario_id=_none_if_missing(raw.get("scenario_id")),
            has_ev=has_ev,
            ev_id=ev_id,
        )
        building_records.append(model.to_record())

        zone_records.append(
            ThermalZone(
                zone_id=f"zone:{building_id}:main",
                building_model_id=model_id,
                building_id=building_id,
                zone_type="conditioned_space",
                archetype_id=archetype.archetype_id,
                floor_area_m2=round(area_m2, 6),
                thermal_resistance_c_per_kw=round(thermal_resistance, 6),
                thermal_capacitance_kwh_per_c=round(thermal_capacitance, 6),
                heating_setpoint_c=21.0,
                cooling_setpoint_c=24.0,
                deadband_c=0.8,
                source_standard=SOURCE_STANDARD,
            ).to_record()
        )

        device_records.extend(
            device.to_record()
            for device in hvac_devices_for_building(
                building_model_id=model_id,
                building_id=building_id,
                heating_capacity_kw=heating_capacity_kw,
                cooling_capacity_kw=cooling_capacity_kw,
                source_standard=SOURCE_STANDARD,
            )
        )
        if include_evse and has_ev and ev_id:
            device_records.append(
                evse_device_for_building(
                    building_model_id=model_id,
                    building_id=building_id,
                    ev_id=ev_id,
                    source_standard=SOURCE_STANDARD,
                ).to_record()
            )

        annual_factor = archetype.annual_kwh_per_m2 * area_m2
        end_uses = [
            ("space_heating", heating_capacity_kw, annual_factor * 0.45, True),
            ("space_cooling", cooling_capacity_kw, annual_factor * 0.12, True),
            ("non_hvac_background", base_load_kw, annual_factor * 0.43, False),
        ]
        for end_use_type, peak_kw, annual_kwh, controllable in end_uses:
            end_use_records.append(
                EndUseLoad(
                    end_use_id=f"end_use:{building_id}:{end_use_type}",
                    building_model_id=model_id,
                    building_id=building_id,
                    end_use_type=end_use_type,
                    peak_kw=round(float(peak_kw), 6),
                    annual_kwh_estimate=round(float(annual_kwh), 6),
                    controllable=controllable,
                    source_standard=SOURCE_STANDARD,
                ).to_record()
            )

    return {
        "building_models": pd.DataFrame.from_records(building_records),
        "thermal_zones": pd.DataFrame.from_records(zone_records),
        "device_registry": pd.DataFrame.from_records(device_records),
        "end_use_loads": pd.DataFrame.from_records(end_use_records),
    }
