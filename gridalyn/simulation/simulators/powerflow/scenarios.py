"""Standard operating-scenario runners for pandapower feeders."""

from __future__ import annotations

from dataclasses import dataclass

import pandapower as pp
import pandas as pd

from gridalyn.simulation.backends.registry import solve_power_flow
from gridalyn.simulation.observation.contract import observe_network


@dataclass(frozen=True)
class StandardPowerflowScenario:
    """Declarative load/PV/EV operating case for a pandapower network."""

    scenario_id: str
    description: str
    load_multiplier: float = 1.0
    pv_buses: tuple[int, ...] = ()
    pv_mw_per_bus: float = 0.0
    ev_buses: tuple[int, ...] = ()
    ev_mw_per_bus: float = 0.0


def scenario_to_record(scenario: StandardPowerflowScenario) -> dict[str, object]:
    """Serialize a standard scenario declaration for project inputs."""
    return {
        "scenario_id": scenario.scenario_id,
        "description": scenario.description,
        "load_multiplier": scenario.load_multiplier,
        "pv_buses": " ".join(str(bus) for bus in scenario.pv_buses),
        "pv_mw_per_bus": scenario.pv_mw_per_bus,
        "ev_buses": " ".join(str(bus) for bus in scenario.ev_buses),
        "ev_mw_per_bus": scenario.ev_mw_per_bus,
    }


def apply_standard_powerflow_scenario(
    net: pp.pandapowerNet,
    scenario: StandardPowerflowScenario,
) -> None:
    """Apply load growth, distributed PV, and EV charging to a pandapower net."""
    net.load["p_mw"] = net.load["p_mw"] * scenario.load_multiplier
    net.load["q_mvar"] = net.load["q_mvar"] * scenario.load_multiplier

    for bus in scenario.pv_buses:
        pp.create_sgen(
            net,
            bus=int(bus),
            p_mw=float(scenario.pv_mw_per_bus),
            q_mvar=0.0,
            name=f"{scenario.scenario_id}_pv_bus_{int(bus)}",
            type="PV",
        )

    for bus in scenario.ev_buses:
        pp.create_load(
            net,
            bus=int(bus),
            p_mw=float(scenario.ev_mw_per_bus),
            q_mvar=float(scenario.ev_mw_per_bus) * 0.25,
            name=f"{scenario.scenario_id}_ev_bus_{int(bus)}",
            type="EV",
        )


def run_standard_powerflow_scenario(
    net: pp.pandapowerNet,
    scenario: StandardPowerflowScenario,
    *,
    algorithm: str = "nr",
    init: str = "auto",
) -> tuple[dict[str, object], pd.DataFrame]:
    """Apply and solve a standard operating scenario."""
    apply_standard_powerflow_scenario(net, scenario)
    solve_power_flow(net, algorithm=algorithm, init=init)

    observation = observe_network(net)
    voltage = observation.voltage_frame()
    voltage["scenario_id"] = scenario.scenario_id
    total_generation_mw = float(net.sgen.p_mw.sum()) if len(net.sgen) else 0.0
    total_load_mw = float(net.load.p_mw.sum())
    under_voltage, over_voltage = observation.voltage_violation_counts(
        below_pu=0.95,
        above_pu=1.05,
    )
    result = {
        "scenario_id": scenario.scenario_id,
        "description": scenario.description,
        "load_multiplier": scenario.load_multiplier,
        "pv_bus_count": len(scenario.pv_buses),
        "pv_total_mw": len(scenario.pv_buses) * scenario.pv_mw_per_bus,
        "ev_bus_count": len(scenario.ev_buses),
        "ev_total_mw": len(scenario.ev_buses) * scenario.ev_mw_per_bus,
        "converged": observation.converged,
        "total_load_mw": total_load_mw,
        "total_generation_mw": total_generation_mw,
        "net_demand_mw": total_load_mw - total_generation_mw,
        "line_loss_mw": observation.total_line_loss_mw,
        "min_voltage_pu": observation.min_voltage_pu,
        "max_voltage_pu": observation.max_voltage_pu,
        "max_line_loading_percent": observation.max_line_loading_percent,
        "voltage_violation_count": under_voltage + over_voltage,
    }
    return result, voltage


__all__ = [
    "StandardPowerflowScenario",
    "apply_standard_powerflow_scenario",
    "run_standard_powerflow_scenario",
    "scenario_to_record",
]
