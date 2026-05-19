import pandas as pd
import pandapower as pp

from gridalyn.assets import (
    BatteryAsset,
    ProsumerAsset,
    PVAsset,
    apply_battery_dispatch_to_pandapower,
    apply_pv_generation_to_pandapower,
    prosumer_assets_to_frame,
)


def test_prosumer_assets_have_stable_tabular_contract() -> None:
    assets = [
        ProsumerAsset(
            prosumer_id="P01",
            bus_id=4,
            pv=PVAsset(asset_id="pv:P01", capacity_mw=0.18),
            battery=BatteryAsset(
                asset_id="battery:P01",
                power_mw=0.12,
                capacity_mwh=0.36,
                initial_soc_mwh=0.25,
                min_soc_mwh=0.07,
            ),
            offer_price_usd_per_mwh=58.0,
        )
    ]

    frame = prosumer_assets_to_frame(assets)

    assert list(frame.columns) == [
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
    ]
    assert frame.iloc[0].to_dict()["prosumer_id"] == "P01"
    assert frame.iloc[0].to_dict()["battery_power_mw"] == 0.12


def test_prosumer_assets_can_be_applied_to_pandapower() -> None:
    net = pp.create_empty_network(sn_mva=1.0)
    bus = pp.create_bus(net, vn_kv=12.47)
    pp.create_ext_grid(net, bus=bus)
    prosumers = pd.DataFrame(
        [
            {
                "prosumer_id": "P01",
                "bus_id": bus,
                "pv_capacity_mw": 0.18,
            }
        ]
    )
    dispatch = pd.DataFrame(
        [
            {
                "prosumer_id": "P01",
                "bus_id": bus,
                "dispatch_mw": 0.08,
            }
        ]
    )

    apply_pv_generation_to_pandapower(net, prosumers, pv_factor=0.5)
    apply_battery_dispatch_to_pandapower(net, dispatch)

    assert list(net.sgen["type"]) == ["PV", "battery_discharge"]
    assert list(net.sgen["p_mw"]) == [0.09, 0.08]
