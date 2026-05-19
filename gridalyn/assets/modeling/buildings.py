"""Building entity records used by the modeling synthesis layer."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class BuildingModel:
    model_id: str
    building_id: str
    load_id: str | None
    load_bus_id: str | None
    lv_bus_id: str | None
    lv_transformer_id: str | None
    lv_feeder_bus_id: str | None
    lv_cluster: str | None
    archetype_id: str
    model_profile: str
    source_standard: str
    source_table: str
    source_id: str
    floor_area_m2: float
    dwelling_units: int
    static_p_kw: float
    base_load_kw: float
    heating_capacity_kw: float
    cooling_capacity_kw: float
    thermal_resistance_c_per_kw: float
    thermal_capacitance_kwh_per_c: float
    flexibility_class: str
    scenario_id: str | None
    has_ev: bool
    ev_id: str | None

    def to_record(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ThermalZone:
    zone_id: str
    building_model_id: str
    building_id: str
    zone_type: str
    archetype_id: str
    floor_area_m2: float
    thermal_resistance_c_per_kw: float
    thermal_capacitance_kwh_per_c: float
    heating_setpoint_c: float
    cooling_setpoint_c: float
    deadband_c: float
    source_standard: str

    def to_record(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class EndUseLoad:
    end_use_id: str
    building_model_id: str
    building_id: str
    end_use_type: str
    peak_kw: float
    annual_kwh_estimate: float
    controllable: bool
    source_standard: str

    def to_record(self) -> dict[str, object]:
        return asdict(self)
