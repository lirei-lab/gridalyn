import numpy as np
import pytest

from gridalyn.operations.der_voltage import measure_local_voltage_sensitivity
from gridalyn.simulation.control.tabular_voltage import (
    TabularRLPolicy,
    TabularVoltageControlConfig,
    _select_action,
)
from gridalyn.simulation.observation.contract import NetworkObservation
from gridalyn.simulation.policies.contract import (
    SENSITIVITY_DISPATCH_POLICY_ID,
    TABULAR_RL_POLICY_ID,
    voltage_at_bus,
)
from gridalyn.simulation.policies.registry import (
    SensitivityDispatchPolicy,
    UnknownPolicyError,
    default_policy_registry,
)


def _observation(bus_ids, voltages) -> NetworkObservation:
    return NetworkObservation(
        converged=True,
        bus_ids=np.asarray(bus_ids),
        bus_voltage_pu=np.asarray(voltages, dtype=float),
        line_loading_percent=np.empty(0, dtype=float),
        total_line_loss_mw=None,
    )


def test_default_registry_lists_both_policies() -> None:
    registry = default_policy_registry()

    ids = [descriptor.policy_id for descriptor in registry.list_descriptors()]

    assert ids == sorted([SENSITIVITY_DISPATCH_POLICY_ID, TABULAR_RL_POLICY_ID])
    assert len(ids) >= 2


def test_unknown_policy_id_raises_located_error_enumerating_available_ids() -> None:
    registry = default_policy_registry()

    with pytest.raises(UnknownPolicyError) as excinfo:
        registry.create("not_a_real_policy")

    message = str(excinfo.value)
    assert "not_a_real_policy" in message
    assert SENSITIVITY_DISPATCH_POLICY_ID in message
    assert TABULAR_RL_POLICY_ID in message


def test_voltage_at_bus_looks_up_by_id_not_position() -> None:
    observation = _observation(bus_ids=[5, 2, 9], voltages=[1.00, 1.02, 0.97])

    assert voltage_at_bus(observation, 2) == 1.02
    assert voltage_at_bus(observation, 9) == 0.97


def test_voltage_at_bus_raises_for_an_unobserved_bus() -> None:
    observation = _observation(bus_ids=[5, 2, 9], voltages=[1.00, 1.02, 0.97])

    with pytest.raises(ValueError, match="bus_id 42 not present"):
        voltage_at_bus(observation, 42)


def test_sensitivity_dispatch_policy_steers_toward_target() -> None:
    policy = SensitivityDispatchPolicy(
        sensitivity_pu_per_mw=0.05,
        action_space_mw=(-0.08, 0.0, 0.08),
        controlled_bus_id=3,
        voltage_target_pu=1.01,
    )
    below_target = _observation(bus_ids=[3], voltages=[1.00])
    above_target = _observation(bus_ids=[3], voltages=[1.02])

    discharge = policy.decide(below_target, soc_mwh=0.12, step=0)
    charge = policy.decide(above_target, soc_mwh=0.12, step=0)

    assert discharge > 0
    assert charge < 0


def test_sensitivity_dispatch_policy_clips_to_action_space_bounds() -> None:
    policy = SensitivityDispatchPolicy(
        sensitivity_pu_per_mw=0.001,
        action_space_mw=(-0.08, 0.0, 0.08),
        controlled_bus_id=3,
        voltage_target_pu=1.01,
    )
    far_below_target = _observation(bus_ids=[3], voltages=[0.90])

    action = policy.decide(far_below_target, soc_mwh=0.12, step=0)

    assert action == 0.08


def test_sensitivity_dispatch_policy_rejects_zero_sensitivity() -> None:
    with pytest.raises(ValueError, match="non-zero"):
        SensitivityDispatchPolicy(
            sensitivity_pu_per_mw=0.0,
            action_space_mw=(-0.08, 0.0, 0.08),
            controlled_bus_id=3,
            voltage_target_pu=1.01,
        )


def test_measure_local_voltage_sensitivity_matches_battery_discharge_direction() -> (
    None
):
    from gridalyn.assets import BatteryAsset, RadialFeederSpec, VoltageControlDERSpec

    der = VoltageControlDERSpec(
        asset_id="der:policy:test",
        controlled_bus_id=3,
        pv_bus_id=3,
        battery_bus_id=3,
        pv_capacity_mw=0.35,
        battery=BatteryAsset(
            asset_id="battery:policy:test",
            power_mw=0.08,
            capacity_mwh=0.24,
            initial_soc_mwh=0.12,
            min_soc_mwh=0.04,
        ),
        max_soc_mwh=0.22,
        action_space_mw=(-0.08, 0.0, 0.08),
    )
    feeder = RadialFeederSpec(
        name="policy_test_feeder",
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

    sensitivity = measure_local_voltage_sensitivity(feeder, der)

    # Discharging more (higher sgen output) must raise the controlled bus's
    # voltage on a radial feeder -- a negative or zero sensitivity here would
    # mean the finite-difference measurement is backwards.
    assert sensitivity > 0.0


def test_tabular_rl_policy_matches_select_action_directly() -> None:
    action_space = (-0.08, 0.0, 0.08)
    q_table = {
        (1, 1, 0, -0.08): 0.1,
        (1, 1, 0, 0.0): 0.9,
        (1, 1, 0, 0.08): 0.2,
    }
    config = TabularVoltageControlConfig()
    policy = TabularRLPolicy(
        q_table=q_table,
        action_space_mw=action_space,
        controlled_bus_id=3,
        config=config,
    )
    # vm=1.01 is between voltage_low_bin_pu (0.995) and voltage_high_bin_pu
    # (1.025) -> voltage_bin=1. soc_mwh=0.20 is between soc_low_bin_mwh
    # (0.16) and soc_high_bin_mwh (0.30) -> soc_bin=1. step=0 is the time
    # bin directly. Together: state (1, 1, 0), matching the seeded key above.
    observation = _observation(bus_ids=[3], voltages=[1.01])

    decided = policy.decide(observation, soc_mwh=0.20, step=0)
    expected = _select_action(
        q_table,
        (1, 1, 0),
        action_space,
        0.0,
        np.random.default_rng(0),
    )

    assert decided == expected
