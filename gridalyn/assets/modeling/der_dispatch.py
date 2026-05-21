"""DER dispatch asset contracts for voltage-constrained operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from gridalyn.assets.modeling.feeders import RadialFeederSpec


@dataclass(frozen=True)
class DERDispatchAsset:
    """PV and battery charging capability attached to one feeder bus."""

    der_id: str
    bus_id: int
    pv_available_mw: float
    battery_charge_power_mw: float


def der_dispatch_assets_to_frame(
    assets: Iterable[DERDispatchAsset],
) -> pd.DataFrame:
    """Convert DER dispatch assets into the canonical tabular contract."""
    return pd.DataFrame(
        [
            {
                "der_id": asset.der_id,
                "bus_id": int(asset.bus_id),
                "pv_available_mw": float(asset.pv_available_mw),
                "battery_charge_power_mw": float(asset.battery_charge_power_mw),
            }
            for asset in assets
        ],
        columns=[
            "der_id",
            "bus_id",
            "pv_available_mw",
            "battery_charge_power_mw",
        ],
    )


def validate_der_dispatch_assets(
    feeder: RadialFeederSpec,
    assets: Iterable[DERDispatchAsset],
) -> None:
    """Validate DER dispatch assets against a feeder model contract."""
    seen: set[str] = set()
    for asset in assets:
        if asset.der_id in seen:
            raise ValueError(f"duplicate DER asset id: {asset.der_id}")
        seen.add(asset.der_id)
        if int(asset.bus_id) <= 0 or int(asset.bus_id) >= feeder.bus_count:
            raise ValueError(f"{asset.der_id} has invalid bus_id {asset.bus_id}")
        if asset.pv_available_mw < 0:
            raise ValueError(f"{asset.der_id} pv_available_mw must be non-negative")
        if asset.battery_charge_power_mw < 0:
            raise ValueError(f"{asset.der_id} battery_charge_power_mw must be non-negative")


__all__ = [
    "DERDispatchAsset",
    "der_dispatch_assets_to_frame",
    "validate_der_dispatch_assets",
]
