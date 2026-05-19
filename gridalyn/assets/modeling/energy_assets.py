"""Reusable energy-asset contracts for prosumer and DER studies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd
import pandapower as pp


@dataclass(frozen=True)
class PVAsset:
    """Static PV capability connected through a prosumer or network asset."""

    asset_id: str
    capacity_mw: float


@dataclass(frozen=True)
class BatteryAsset:
    """Battery capability and operating state bounds."""

    asset_id: str
    power_mw: float
    capacity_mwh: float
    initial_soc_mwh: float
    min_soc_mwh: float


@dataclass(frozen=True)
class ProsumerAsset:
    """Prosumer with colocated PV and battery resources."""

    prosumer_id: str
    bus_id: int
    pv: PVAsset
    battery: BatteryAsset
    offer_price_usd_per_mwh: float


def prosumer_assets_to_frame(assets: Iterable[ProsumerAsset]) -> pd.DataFrame:
    """Convert prosumer assets to the stable tabular project contract."""
    rows = [
        {
            "prosumer_id": asset.prosumer_id,
            "bus_id": asset.bus_id,
            "pv_asset_id": asset.pv.asset_id,
            "pv_capacity_mw": asset.pv.capacity_mw,
            "battery_asset_id": asset.battery.asset_id,
            "battery_power_mw": asset.battery.power_mw,
            "battery_capacity_mwh": asset.battery.capacity_mwh,
            "initial_soc_mwh": asset.battery.initial_soc_mwh,
            "min_soc_mwh": asset.battery.min_soc_mwh,
            "offer_price_usd_per_mwh": asset.offer_price_usd_per_mwh,
        }
        for asset in assets
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "prosumer_id",
            "bus_id",
            "pv_asset_id",
            "pv_capacity_mw",
            "battery_asset_id",
            "battery_power_mw",
            "battery_capacity_mwh",
            "initial_soc_mwh",
            "min_soc_mwh",
            "offer_price_usd_per_mwh",
        ],
    )


def apply_pv_generation_to_pandapower(
    net: pp.pandapowerNet,
    prosumers: pd.DataFrame,
    *,
    pv_factor: float,
) -> list[int]:
    """Add PV static generators for prosumer rows and return element IDs."""
    element_ids: list[int] = []
    for row in prosumers.itertuples(index=False):
        element_ids.append(
            pp.create_sgen(
                net,
                bus=int(row.bus_id),
                p_mw=float(row.pv_capacity_mw) * pv_factor,
                q_mvar=0.0,
                name=f"{row.prosumer_id}_pv",
                type="PV",
            )
        )
    return element_ids


def apply_battery_dispatch_to_pandapower(
    net: pp.pandapowerNet,
    dispatch: pd.DataFrame,
) -> list[int]:
    """Add dispatched battery injections as pandapower static generators."""
    element_ids: list[int] = []
    for row in dispatch.itertuples(index=False):
        if float(row.dispatch_mw) <= 0:
            continue
        element_ids.append(
            pp.create_sgen(
                net,
                bus=int(row.bus_id),
                p_mw=float(row.dispatch_mw),
                q_mvar=0.0,
                name=f"{row.prosumer_id}_battery",
                type="battery_discharge",
            )
        )
    return element_ids
