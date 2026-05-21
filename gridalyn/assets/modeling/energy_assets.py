"""Reusable energy-asset contracts for prosumer and DER studies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd


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


__all__ = [
    "BatteryAsset",
    "PVAsset",
    "ProsumerAsset",
    "prosumer_assets_to_frame",
]
