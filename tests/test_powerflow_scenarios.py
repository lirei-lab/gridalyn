from __future__ import annotations

import pandapower as pp
import pytest

from gridalyn.simulation.simulators.powerflow import (
    StandardPowerflowScenario,
    run_standard_powerflow_scenario,
)


def _base_network() -> pp.pandapowerNet:
    net = pp.create_empty_network(sn_mva=1.0)
    pp.create_bus(net, vn_kv=12.47)
    pp.create_bus(net, vn_kv=12.47)
    pp.create_ext_grid(net, bus=0, vm_pu=1.0)
    pp.create_line_from_parameters(
        net,
        from_bus=0,
        to_bus=1,
        length_km=0.1,
        r_ohm_per_km=0.2,
        x_ohm_per_km=0.1,
        c_nf_per_km=5.0,
        max_i_ka=0.2,
    )
    pp.create_load(net, bus=1, p_mw=0.05, q_mvar=0.01)
    return net


def test_standard_powerflow_scenario_applies_load_pv_and_ev_cases() -> None:
    scenario = StandardPowerflowScenario(
        scenario_id="stress_case",
        description="Load growth with PV and EV.",
        load_multiplier=2.0,
        pv_buses=(1,),
        pv_mw_per_bus=0.01,
        ev_buses=(1,),
        ev_mw_per_bus=0.02,
    )

    result, voltage = run_standard_powerflow_scenario(_base_network(), scenario)

    assert result["scenario_id"] == "stress_case"
    assert result["converged"] is True
    assert result["total_load_mw"] == pytest.approx(0.12)
    assert result["total_generation_mw"] == pytest.approx(0.01)
    assert result["net_demand_mw"] == pytest.approx(0.11)
    assert list(voltage["scenario_id"].unique()) == ["stress_case"]
