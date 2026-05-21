"""Deterministic synthetic feeder used by the prosumer market demo."""

from __future__ import annotations

from gridalyn.assets import BatteryAsset, PVAsset, ProsumerAsset, RadialFeederSpec
from gridalyn.simulation import build_radial_pandapower_feeder


LOADS_MW = {
    1: 0.12,
    2: 0.16,
    3: 0.18,
    4: 0.20,
    5: 0.14,
    6: 0.22,
    7: 0.17,
    8: 0.24,
    9: 0.21,
    10: 0.19,
    11: 0.23,
    12: 0.18,
    13: 0.16,
}

PROSUMER_ASSETS = (
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
    ),
    ProsumerAsset(
        prosumer_id="P02",
        bus_id=6,
        pv=PVAsset(asset_id="pv:P02", capacity_mw=0.22),
        battery=BatteryAsset(
            asset_id="battery:P02",
            power_mw=0.14,
            capacity_mwh=0.42,
            initial_soc_mwh=0.30,
            min_soc_mwh=0.08,
        ),
        offer_price_usd_per_mwh=52.0,
    ),
    ProsumerAsset(
        prosumer_id="P03",
        bus_id=8,
        pv=PVAsset(asset_id="pv:P03", capacity_mw=0.20),
        battery=BatteryAsset(
            asset_id="battery:P03",
            power_mw=0.13,
            capacity_mwh=0.40,
            initial_soc_mwh=0.28,
            min_soc_mwh=0.08,
        ),
        offer_price_usd_per_mwh=55.0,
    ),
    ProsumerAsset(
        prosumer_id="P04",
        bus_id=10,
        pv=PVAsset(asset_id="pv:P04", capacity_mw=0.24),
        battery=BatteryAsset(
            asset_id="battery:P04",
            power_mw=0.15,
            capacity_mwh=0.45,
            initial_soc_mwh=0.32,
            min_soc_mwh=0.09,
        ),
        offer_price_usd_per_mwh=49.0,
    ),
    ProsumerAsset(
        prosumer_id="P05",
        bus_id=12,
        pv=PVAsset(asset_id="pv:P05", capacity_mw=0.21),
        battery=BatteryAsset(
            asset_id="battery:P05",
            power_mw=0.14,
            capacity_mwh=0.42,
            initial_soc_mwh=0.31,
            min_soc_mwh=0.08,
        ),
        offer_price_usd_per_mwh=51.0,
    ),
)

FEEDER_SPEC = RadialFeederSpec(
    name="synthetic_14_bus_radial_feeder",
    bus_count=14,
    sn_mva=5.0,
    base_voltage_kv=12.47,
    slack_vm_pu=1.02,
    loads_mw=LOADS_MW,
    q_to_p_ratio=0.32,
    line_length_km=0.35,
    line_lengths_km={to_bus: 0.35 + 0.03 * (to_bus % 4) for to_bus in range(1, 14)},
    line_r_ohm_per_km=0.38,
    line_x_ohm_per_km=0.32,
    line_c_nf_per_km=8.0,
    line_max_i_ka=0.22,
    bus_y_step=0.35,
    metadata={"source": "gridalyn.assets.modeling.feeders.RadialFeederSpec"},
)


def build_synthetic_feeder():
    """Create a compact 14-bus radial feeder with deterministic loads."""
    return build_radial_pandapower_feeder(FEEDER_SPEC)
