"""Synthetic feeder and DER definitions for voltage optimization."""

from __future__ import annotations

from gridalyn.assets import DERDispatchAsset, RadialFeederSpec
from gridalyn.simulation import build_radial_pandapower_feeder


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
    DERDispatchAsset("DER01", bus_id=8, pv_available_mw=0.52, battery_charge_power_mw=0.16),
    DERDispatchAsset("DER02", bus_id=10, pv_available_mw=0.58, battery_charge_power_mw=0.18),
    DERDispatchAsset("DER03", bus_id=12, pv_available_mw=0.56, battery_charge_power_mw=0.18),
    DERDispatchAsset("DER04", bus_id=14, pv_available_mw=0.62, battery_charge_power_mw=0.20),
    DERDispatchAsset("DER05", bus_id=15, pv_available_mw=0.48, battery_charge_power_mw=0.16),
)

FEEDER_SPEC = RadialFeederSpec(
    name="synthetic_16_bus_der_feeder",
    bus_count=16,
    sn_mva=5.0,
    base_voltage_kv=12.47,
    slack_vm_pu=1.02,
    loads_mw=LOADS_MW,
    q_to_p_ratio=0.28,
    line_length_km=0.65,
    line_lengths_km={to_bus: 0.65 + 0.04 * (to_bus % 3) for to_bus in range(1, 16)},
    line_r_ohm_per_km=0.58,
    line_x_ohm_per_km=0.36,
    line_c_nf_per_km=6.0,
    line_max_i_ka=0.18,
    bus_y_step=0.2,
    metadata={"source": "gridalyn.assets.modeling.feeders.RadialFeederSpec"},
)


def build_der_feeder():
    """Create a compact radial feeder where high downstream PV can overvoltage."""
    return build_radial_pandapower_feeder(FEEDER_SPEC)
