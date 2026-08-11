"""Pandapower mappings for DER dispatch study contracts."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pandapower as pp
import pandas as pd

from gridalyn.simulation.backends.registry import solve_power_flow


def apply_der_dispatch_setpoints_to_pandapower(
    net: pp.pandapowerNet,
    der_assets: pd.DataFrame,
    pv_dispatch_mw: np.ndarray,
    battery_charge_mw: np.ndarray,
) -> list[int]:
    """Attach DER PV dispatch and battery-charge setpoints to a pandapower net."""
    element_ids: list[int] = []
    for idx, row in enumerate(der_assets.itertuples(index=False)):
        element_ids.append(
            pp.create_sgen(
                net,
                bus=int(row.bus_id),
                p_mw=float(pv_dispatch_mw[idx]),
                q_mvar=0.0,
                name=f"{row.der_id}_pv_dispatch",
                type="PV",
            )
        )
        if float(battery_charge_mw[idx]) > 0:
            element_ids.append(
                pp.create_load(
                    net,
                    bus=int(row.bus_id),
                    p_mw=float(battery_charge_mw[idx]),
                    q_mvar=0.0,
                    name=f"{row.der_id}_battery_charge",
                    type="battery_charge",
                )
            )
    return element_ids


def build_der_dispatch_pandapower_network(
    build_feeder: Callable[[], pp.pandapowerNet],
    der_assets: pd.DataFrame,
    pv_dispatch_mw: np.ndarray,
    battery_charge_mw: np.ndarray,
    *,
    run_powerflow: bool = True,
) -> pp.pandapowerNet:
    """Build a feeder snapshot with DER dispatch setpoints applied."""
    net = build_feeder()
    apply_der_dispatch_setpoints_to_pandapower(
        net,
        der_assets,
        pv_dispatch_mw,
        battery_charge_mw,
    )
    if run_powerflow:
        solve_power_flow(net)
    return net


__all__ = [
    "apply_der_dispatch_setpoints_to_pandapower",
    "build_der_dispatch_pandapower_network",
]
