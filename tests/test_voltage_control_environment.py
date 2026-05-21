import numpy as np

from gridalyn.assets import (
    BatteryAsset,
    RadialFeederSpec,
    VoltageControlDERSpec,
    voltage_control_assets_to_frame,
)
from gridalyn.simulation import (
    VoltageControlEnvironment,
    VoltageControlEnvironmentSpec,
    build_voltage_control_feeder,
)
from gridalyn import (
    RadialFeederSpec as RootRadialFeederSpec,
    VoltageControlEnvironment as RootVoltageControlEnvironment,
)


def _problem_spec() -> VoltageControlEnvironmentSpec:
    load_profile = np.array([0.9, 1.1], dtype=float)
    pv_profile = np.array([0.0, 0.75], dtype=float)
    der = VoltageControlDERSpec(
        asset_id="der:rl:test",
        controlled_bus_id=3,
        pv_bus_id=3,
        battery_bus_id=3,
        pv_capacity_mw=0.35,
        battery=BatteryAsset(
            asset_id="battery:rl:test",
            power_mw=0.08,
            capacity_mwh=0.24,
            initial_soc_mwh=0.12,
            min_soc_mwh=0.04,
        ),
        max_soc_mwh=0.22,
        action_space_mw=(-0.08, 0.0, 0.08),
    )
    feeder = RadialFeederSpec(
        name="test_voltage_control_feeder",
        bus_count=4,
        sn_mva=1.0,
        base_voltage_kv=12.47,
        slack_vm_pu=1.01,
        loads_mw={1: 0.04, 2: 0.05, 3: 0.06},
        line_length_km=0.25,
        line_r_ohm_per_km=0.55,
        line_x_ohm_per_km=0.30,
        line_c_nf_per_km=5.0,
        line_max_i_ka=0.12,
    )
    return VoltageControlEnvironmentSpec(
        feeder=feeder,
        der=der,
        load_multiplier_profile=load_profile,
        pv_profile=pv_profile,
        timestep_hours=0.25,
        voltage_target_pu=1.01,
        voltage_low_pu=0.98,
        voltage_high_pu=1.04,
    )


def test_voltage_control_feeder_is_gridalyn_modeled() -> None:
    spec = _problem_spec()

    net = build_voltage_control_feeder(spec.feeder, spec.der)
    assets = voltage_control_assets_to_frame(spec.der)

    assert len(net.bus) == 4
    assert len(net.line) == 3
    assert len(net.load) == 4
    assert list(net.sgen["name"]) == ["pv_plant", "battery_discharge"]
    assert assets.iloc[0].to_dict()["asset_id"] == "der:rl:test"
    assert assets.iloc[0].to_dict()["battery_power_mw"] == 0.08
    assert RootRadialFeederSpec is RadialFeederSpec
    assert RootVoltageControlEnvironment is VoltageControlEnvironment


def test_voltage_control_environment_applies_actions_and_returns_metrics() -> None:
    env = VoltageControlEnvironment(_problem_spec())

    env.reset()
    idle = env.step(0, 0.0)
    discharge = env.step(1, 0.08)

    assert idle["step"] == 0
    assert discharge["step"] == 1
    assert discharge["action_mw"] == 0.08
    assert discharge["soc_mwh"] < 0.12
    assert 0.90 < discharge["controlled_vm_pu"] < 1.10
    assert set(discharge).issuperset(
        {
            "pv_mw",
            "action_mw",
            "soc_mwh",
            "controlled_vm_pu",
            "max_vm_pu",
            "min_vm_pu",
            "voltage_violation",
            "reward",
        }
    )
