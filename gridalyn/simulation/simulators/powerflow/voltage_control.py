"""Pandapower builders for voltage-control asset contracts."""

from __future__ import annotations

import pandapower as pp

from gridalyn.assets.modeling.feeders import RadialFeederSpec
from gridalyn.assets.modeling.voltage_control import (
    VoltageControlDERSpec,
    validate_voltage_control_der,
)
from gridalyn.simulation.simulators.powerflow.feeders import (
    build_radial_pandapower_feeder,
)


def build_voltage_control_feeder(
    feeder: RadialFeederSpec,
    der: VoltageControlDERSpec,
) -> pp.pandapowerNet:
    """Build a radial feeder with named PV and battery control elements."""
    validate_voltage_control_der(feeder, der)
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


__all__ = ["build_voltage_control_feeder"]
