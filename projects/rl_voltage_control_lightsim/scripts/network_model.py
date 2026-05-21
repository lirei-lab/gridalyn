"""Gridalyn-backed model specification for RL voltage-control experiments."""

from __future__ import annotations

import numpy as np

from gridalyn.assets import (
    BatteryAsset,
    RadialFeederSpec,
    VoltageControlDERSpec,
)
from gridalyn.simulation import VoltageControlEnvironmentSpec, build_voltage_control_feeder


BASE_LOADS_MW = {
    1: 0.08,
    2: 0.09,
    3: 0.10,
    4: 0.11,
    5: 0.10,
    6: 0.09,
    7: 0.08,
    8: 0.07,
    9: 0.06,
}
BATTERY_BUS = 9
PV_BUS = 9
PV_MAX_MW = 1.25
BATTERY_POWER_MW = 0.12
BATTERY_CAPACITY_MWH = 0.42
INITIAL_SOC_MWH = 0.20
MIN_SOC_MWH = 0.05
MAX_SOC_MWH = 0.40
ACTION_MW = (-BATTERY_POWER_MW, 0.0, BATTERY_POWER_MW)

FEEDER_SPEC = RadialFeederSpec(
    name="synthetic_10_bus_rl_feeder",
    bus_count=10,
    sn_mva=2.0,
    base_voltage_kv=12.47,
    slack_vm_pu=1.01,
    loads_mw=BASE_LOADS_MW,
    q_to_p_ratio=0.30,
    line_length_km=0.85,
    line_lengths_km={to_bus: 0.85 + 0.05 * (to_bus % 2) for to_bus in range(1, 10)},
    line_r_ohm_per_km=0.82,
    line_x_ohm_per_km=0.44,
    line_c_nf_per_km=5.0,
    line_max_i_ka=0.16,
    bus_y_step=0.18,
    metadata={"source": "gridalyn.assets.modeling.feeders.RadialFeederSpec"},
)

DER_SPEC = VoltageControlDERSpec(
    asset_id="der:rl_voltage_control",
    controlled_bus_id=BATTERY_BUS,
    pv_bus_id=PV_BUS,
    battery_bus_id=BATTERY_BUS,
    pv_capacity_mw=PV_MAX_MW,
    battery=BatteryAsset(
        asset_id="battery:rl_voltage_control",
        power_mw=BATTERY_POWER_MW,
        capacity_mwh=BATTERY_CAPACITY_MWH,
        initial_soc_mwh=INITIAL_SOC_MWH,
        min_soc_mwh=MIN_SOC_MWH,
    ),
    max_soc_mwh=MAX_SOC_MWH,
    action_space_mw=ACTION_MW,
)


def load_multiplier_profile() -> np.ndarray:
    return np.array(
        [
            0.72,
            0.70,
            0.69,
            0.70,
            0.76,
            0.86,
            0.96,
            1.02,
            1.04,
            0.98,
            0.90,
            0.82,
            0.76,
            0.74,
            0.78,
            0.86,
            0.98,
            1.12,
            1.22,
            1.26,
            1.18,
            1.02,
            0.88,
            0.78,
        ],
        dtype=float,
    )


def pv_profile() -> np.ndarray:
    return np.array(
        [
            0.0,
            0.0,
            0.0,
            0.0,
            0.02,
            0.08,
            0.20,
            0.42,
            0.62,
            0.82,
            0.96,
            1.00,
            0.98,
            0.88,
            0.68,
            0.44,
            0.22,
            0.06,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
        ],
        dtype=float,
    )


def build_rl_feeder():
    """Create the RL feeder using Gridalyn's reusable modeling contracts."""
    return build_voltage_control_feeder(FEEDER_SPEC, DER_SPEC)


def build_rl_environment_spec() -> VoltageControlEnvironmentSpec:
    """Create the Gridalyn voltage-control environment specification."""
    return VoltageControlEnvironmentSpec(
        feeder=FEEDER_SPEC,
        der=DER_SPEC,
        load_multiplier_profile=load_multiplier_profile(),
        pv_profile=pv_profile(),
        timestep_hours=0.25,
        voltage_target_pu=1.01,
        voltage_low_pu=0.98,
        voltage_high_pu=1.04,
    )
