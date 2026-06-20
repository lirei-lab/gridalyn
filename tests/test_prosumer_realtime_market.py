from __future__ import annotations

import pandas as pd
import pandapower as pp

from gridalyn.operations import (
    ProsumerRealtimeMarketConfig,
    run_prosumer_realtime_market,
)


def _feeder() -> pp.pandapowerNet:
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
    pp.create_load(net, bus=1, p_mw=0.4, q_mvar=0.08)
    return net


def test_prosumer_realtime_market_runs_clearing_and_powerflow() -> None:
    prosumers = pd.DataFrame(
        [
            {
                "prosumer_id": "p1",
                "bus_id": 1,
                "battery_power_mw": 0.3,
                "initial_soc_mwh": 1.0,
                "min_soc_mwh": 0.1,
                "offer_price_usd_per_mwh": 35.0,
                "pv_capacity_mw": 0.0,
            }
        ]
    )
    config = ProsumerRealtimeMarketConfig(
        interval_minutes=5,
        interval_count=2,
        import_limit_mw=0.2,
        forecast_horizon_intervals=1,
        load_multipliers=(1.0, 1.0),
        pv_factors=(0.0, 0.0),
        load_forecast_bias_by_lead=(0.0,),
        pv_forecast_bias_by_lead=(0.0,),
    )

    result = run_prosumer_realtime_market(
        prosumers=prosumers,
        build_feeder=_feeder,
        config=config,
    )

    assert len(result.clearing) == 2
    assert len(result.dispatch) == 2
    assert result.clearing["cleared_mw"].sum() > 0.0
    assert result.powerflow["converged"].all()
