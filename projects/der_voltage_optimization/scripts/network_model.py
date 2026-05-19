"""Synthetic feeder and DER definitions for voltage optimization."""

from __future__ import annotations

import pandapower as pp


LOADS_MW = {
    1: 0.04,
    2: 0.05,
    3: 0.05,
    4: 0.06,
    5: 0.04,
    6: 0.05,
    7: 0.05,
    8: 0.04,
    9: 0.04,
    10: 0.05,
    11: 0.04,
    12: 0.05,
    13: 0.04,
    14: 0.04,
    15: 0.04,
}

DER_ASSETS = (
    {"der_id": "DER01", "bus_id": 8, "pv_available_mw": 0.52, "battery_charge_power_mw": 0.16},
    {"der_id": "DER02", "bus_id": 10, "pv_available_mw": 0.58, "battery_charge_power_mw": 0.18},
    {"der_id": "DER03", "bus_id": 12, "pv_available_mw": 0.56, "battery_charge_power_mw": 0.18},
    {"der_id": "DER04", "bus_id": 14, "pv_available_mw": 0.62, "battery_charge_power_mw": 0.20},
    {"der_id": "DER05", "bus_id": 15, "pv_available_mw": 0.48, "battery_charge_power_mw": 0.16},
)


def build_der_feeder() -> pp.pandapowerNet:
    """Create a compact radial feeder where high downstream PV can overvoltage."""
    net = pp.create_empty_network(sn_mva=5.0)
    for bus_id in range(16):
        pp.create_bus(
            net,
            vn_kv=12.47,
            name=f"bus_{bus_id:02d}",
            geodata=(float(bus_id), 0.2 * float(bus_id % 4)),
        )
    pp.create_ext_grid(net, bus=0, vm_pu=1.02, name="grid_connection")

    for from_bus, to_bus in zip(range(15), range(1, 16), strict=True):
        pp.create_line_from_parameters(
            net,
            from_bus=from_bus,
            to_bus=to_bus,
            length_km=0.65 + 0.04 * (to_bus % 3),
            r_ohm_per_km=0.58,
            x_ohm_per_km=0.36,
            c_nf_per_km=6.0,
            max_i_ka=0.18,
            name=f"line_{from_bus:02d}_{to_bus:02d}",
        )

    for bus_id, p_mw in LOADS_MW.items():
        pp.create_load(
            net,
            bus=bus_id,
            p_mw=p_mw,
            q_mvar=p_mw * 0.28,
            name=f"load_bus_{bus_id:02d}",
        )
    return net
