"""Device registry helpers for synthesized building models."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class DeviceModel:
    device_id: str
    building_model_id: str
    building_id: str
    device_type: str
    rated_power_kw: float
    controllable: bool
    flexibility_role: str
    source_standard: str
    ev_id: str | None = None

    def to_record(self) -> dict[str, object]:
        return asdict(self)


def hvac_devices_for_building(
    *,
    building_model_id: str,
    building_id: str,
    heating_capacity_kw: float,
    cooling_capacity_kw: float,
    source_standard: str,
) -> list[DeviceModel]:
    return [
        DeviceModel(
            device_id=f"device:{building_id}:hvac_heating",
            building_model_id=building_model_id,
            building_id=building_id,
            device_type="hvac_heating",
            rated_power_kw=round(float(heating_capacity_kw), 6),
            controllable=True,
            flexibility_role="soft_cls_provider",
            source_standard=source_standard,
        ),
        DeviceModel(
            device_id=f"device:{building_id}:hvac_cooling",
            building_model_id=building_model_id,
            building_id=building_id,
            device_type="hvac_cooling",
            rated_power_kw=round(float(cooling_capacity_kw), 6),
            controllable=True,
            flexibility_role="soft_cls_provider",
            source_standard=source_standard,
        ),
    ]


def evse_device_for_building(
    *,
    building_model_id: str,
    building_id: str,
    ev_id: str,
    rated_power_kw: float = 7.2,
    source_standard: str,
) -> DeviceModel:
    return DeviceModel(
        device_id=f"device:{building_id}:evse_l2",
        building_model_id=building_model_id,
        building_id=building_id,
        device_type="evse_l2",
        rated_power_kw=round(float(rated_power_kw), 6),
        controllable=True,
        flexibility_role="hard_cls_backstop",
        source_standard=source_standard,
        ev_id=ev_id,
    )
