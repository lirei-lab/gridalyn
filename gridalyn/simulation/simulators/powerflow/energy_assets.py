"""Pandapower mappings for Gridalyn energy-asset contracts."""

from __future__ import annotations

import pandas as pd
import pandapower as pp


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


__all__ = [
    "apply_battery_dispatch_to_pandapower",
    "apply_pv_generation_to_pandapower",
]
