"""Asset contracts for voltage-control studies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd
import pandapower as pp

from gridalyn.assets.modeling.energy_assets import BatteryAsset
from gridalyn.assets.modeling.feeders import (
    RadialFeederSpec,
    build_radial_pandapower_feeder,
)


@dataclass(frozen=True)
class VoltageControlDERSpec:
    """PV plus battery asset used by voltage-control algorithms."""

    asset_id: str
    controlled_bus_id: int
    pv_bus_id: int
    battery_bus_id: int
    pv_capacity_mw: float
    battery: BatteryAsset
    max_soc_mwh: float
    action_space_mw: tuple[float, ...]


def build_voltage_control_feeder(
    feeder: RadialFeederSpec,
    der: VoltageControlDERSpec,
) -> pp.pandapowerNet:
    """Build a radial feeder with named PV and battery control elements."""
    _validate_voltage_control_der(feeder, der)
    net = build_radial_pandapower_feeder(feeder)
    pp.create_load(
        net,
        bus=int(der.battery_bus_id),
        p_mw=0.0,
        q_mvar=0.0,
        name="battery_charge",
    )
    pp.create_sgen(
        net,
        bus=int(der.pv_bus_id),
        p_mw=0.0,
        q_mvar=0.0,
        min_q_mvar=0.0,
        max_q_mvar=0.0,
        name="pv_plant",
        type="PV",
    )
    pp.create_sgen(
        net,
        bus=int(der.battery_bus_id),
        p_mw=0.0,
        q_mvar=0.0,
        min_q_mvar=0.0,
        max_q_mvar=0.0,
        name="battery_discharge",
        type="battery",
    )
    return net


def voltage_control_assets_to_frame(
    der: VoltageControlDERSpec | Iterable[VoltageControlDERSpec],
) -> pd.DataFrame:
    """Convert voltage-control DER specs into a stable tabular contract."""
    assets = [der] if isinstance(der, VoltageControlDERSpec) else list(der)
    rows = [
        {
            "asset_id": asset.asset_id,
            "controlled_bus_id": int(asset.controlled_bus_id),
            "pv_bus_id": int(asset.pv_bus_id),
            "battery_bus_id": int(asset.battery_bus_id),
            "pv_capacity_mw": float(asset.pv_capacity_mw),
            "battery_asset_id": asset.battery.asset_id,
            "battery_power_mw": float(asset.battery.power_mw),
            "battery_capacity_mwh": float(asset.battery.capacity_mwh),
            "initial_soc_mwh": float(asset.battery.initial_soc_mwh),
            "min_soc_mwh": float(asset.battery.min_soc_mwh),
            "max_soc_mwh": float(asset.max_soc_mwh),
            "action_space_mw": ";".join(
                str(float(value)) for value in asset.action_space_mw
            ),
        }
        for asset in assets
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "asset_id",
            "controlled_bus_id",
            "pv_bus_id",
            "battery_bus_id",
            "pv_capacity_mw",
            "battery_asset_id",
            "battery_power_mw",
            "battery_capacity_mwh",
            "initial_soc_mwh",
            "min_soc_mwh",
            "max_soc_mwh",
            "action_space_mw",
        ],
    )


def _validate_voltage_control_der(
    feeder: RadialFeederSpec,
    der: VoltageControlDERSpec,
) -> None:
    bus_ids = {
        "controlled_bus_id": der.controlled_bus_id,
        "pv_bus_id": der.pv_bus_id,
        "battery_bus_id": der.battery_bus_id,
    }
    invalid = {
        name: bus_id
        for name, bus_id in bus_ids.items()
        if int(bus_id) < 0 or int(bus_id) >= feeder.bus_count
    }
    if invalid:
        raise ValueError(f"VoltageControlDERSpec has invalid bus ids: {invalid}")
    if der.pv_capacity_mw < 0:
        raise ValueError("VoltageControlDERSpec.pv_capacity_mw must be non-negative")
    if der.max_soc_mwh < der.battery.min_soc_mwh:
        raise ValueError(
            "max_soc_mwh must be greater than or equal to battery.min_soc_mwh"
        )
    if der.battery.initial_soc_mwh < der.battery.min_soc_mwh:
        raise ValueError("battery.initial_soc_mwh must respect battery.min_soc_mwh")
    if der.battery.initial_soc_mwh > der.max_soc_mwh:
        raise ValueError("battery.initial_soc_mwh must respect max_soc_mwh")
    if not der.action_space_mw:
        raise ValueError("VoltageControlDERSpec.action_space_mw must not be empty")
