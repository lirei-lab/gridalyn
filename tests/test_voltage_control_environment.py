import ast
from pathlib import Path

import numpy as np

from gridalyn import RadialFeederSpec as RootRadialFeederSpec
from gridalyn import VoltageControlEnvironment as RootVoltageControlEnvironment
from gridalyn import VoltageControlEnvironmentSpec as RootVoltageControlEnvironmentSpec
from gridalyn.assets import (
    BatteryAsset,
    RadialFeederSpec,
    VoltageControlDERSpec,
    voltage_control_assets_to_frame,
)
from gridalyn.operations.der_voltage import measure_local_voltage_sensitivity
from gridalyn.simulation import (
    VoltageControlEnvironment,
    VoltageControlEnvironmentSpec,
    build_voltage_control_feeder,
)
from gridalyn.simulation.backends.contract import (
    LIGHTSIM2GRID_BACKEND_ID,
    PANDAPOWER_NATIVE_BACKEND_ID,
)
from gridalyn.simulation.control.tabular_voltage import (
    TabularRLPolicy,
    TabularVoltageControlConfig,
    train_tabular_voltage_controller,
)
from gridalyn.simulation.environments.voltage_control import run_policy_episode
from gridalyn.simulation.policies.registry import (
    SensitivityDispatchPolicy,
    UnknownPolicyError,
    default_policy_registry,
)

_VOLTAGE_CONTROL_SOURCE = Path(
    "gridalyn/simulation/environments/voltage_control.py"
).read_text(encoding="utf-8")


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


def _run_episode(spec, backend_id) -> list[dict]:
    env = VoltageControlEnvironment(spec, backend_id=backend_id)
    env.reset()
    actions = [0.0, 0.08, -0.08, 0.08, 0.0, -0.08]
    return [env.step(step, action) for step, action in enumerate(actions)]


def _long_profile_spec() -> VoltageControlEnvironmentSpec:
    base = _problem_spec()
    load_profile = np.array([0.9, 1.1, 1.0, 0.8, 1.2, 0.95], dtype=float)
    pv_profile = np.array([0.0, 0.75, 0.4, 0.1, 0.9, 0.3], dtype=float)
    return VoltageControlEnvironmentSpec(
        feeder=base.feeder,
        der=base.der,
        load_multiplier_profile=load_profile,
        pv_profile=pv_profile,
        timestep_hours=base.timestep_hours,
        voltage_target_pu=base.voltage_target_pu,
        voltage_low_pu=base.voltage_low_pu,
        voltage_high_pu=base.voltage_high_pu,
    )


def test_backend_registry_path_agrees_with_the_pre_decomposition_adapter() -> None:
    """Pins the disclosed backend-swap divergence to a tight, checkable bound.

    Before 10-04, this environment solved every step through
    `LightSimPowerflowAdapter.solve_voltage_magnitudes()` -- a warm-started
    incremental C++ solve that never touched `pandapower.runpp`. It now solves
    through `solve_power_flow` -> `pp.runpp(net, lightsim2grid=True)`, flat-started
    every step. The two are not bit-identical: Newton-Raphson converges to the
    same physical fixed point from two different starting points, not to the
    same floating-point bit pattern. The reference values below were captured
    directly from the pre-decomposition adapter on this exact 6-step episode
    (git-stashed at commit ac6e376c, immediately before 10-04) and are pinned
    here so a *regression* in solver agreement -- not the expected ~1e-13
    noise -- is caught before it could reach the governed
    `rl_voltage_control_lightsim` baseline's much coarser 1e-3 pu tolerance.
    """
    spec = _long_profile_spec()
    pre_decomposition_controlled_vm_pu = [
        1.0097066591136141,
        1.010540671090323,
        1.0098316973664967,
        1.0100413619887185,
        1.0104359658507316,
        1.0097560453302161,
    ]

    episode = _run_episode(spec, LIGHTSIM2GRID_BACKEND_ID)

    for step, (record, reference) in enumerate(
        zip(episode, pre_decomposition_controlled_vm_pu, strict=True)
    ):
        relative_difference = abs(record["controlled_vm_pu"] - reference) / reference
        assert relative_difference < 1e-9, (
            f"step {step}: controlled_vm_pu diverged from the pre-decomposition "
            f"adapter by {relative_difference:.3e} relative, exceeding the "
            "1e-9 regression bound (expected noise floor is ~1e-13)"
        )


def test_environment_defaults_to_the_lightsim2grid_backend() -> None:
    """The default backend_id matches this environment's pre-10-04 behaviour."""
    env = VoltageControlEnvironment(_problem_spec())

    assert env.backend_id == LIGHTSIM2GRID_BACKEND_ID


def test_backend_seam_both_registered_backends_agree() -> None:
    """(a) Both 10-01 backends drive this environment to identical results."""
    spec = _long_profile_spec()

    native = _run_episode(spec, PANDAPOWER_NATIVE_BACKEND_ID)
    lightsim = _run_episode(spec, LIGHTSIM2GRID_BACKEND_ID)

    assert native == lightsim


def test_no_direct_result_table_access_remains_in_the_environment() -> None:
    """(c) AST scan, not a bare grep -- a grep would match this docstring."""
    tree = ast.parse(_VOLTAGE_CONTROL_SOURCE)
    direct_accesses = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in ("res_bus", "res_line"):
            direct_accesses.append(node.attr)

    assert direct_accesses == []


def test_unknown_policy_id_is_rejected_with_available_ids_listed() -> None:
    """(d) Unknown-ID policy resolution raises the located error."""
    registry = default_policy_registry()

    try:
        registry.create("no_such_policy")
        raise AssertionError("expected UnknownPolicyError")
    except UnknownPolicyError as exc:
        assert "no_such_policy" in str(exc)
        assert "sensitivity_dispatch" in str(exc)
        assert "tabular_rl" in str(exc)


def test_public_names_unchanged_from_gridalyn_and_gridalyn_simulation() -> None:
    """(e) Both public facades still export the same class objects."""
    assert RootVoltageControlEnvironment is VoltageControlEnvironment
    assert RootVoltageControlEnvironmentSpec is VoltageControlEnvironmentSpec
    assert VoltageControlEnvironment.__name__ == "VoltageControlEnvironment"
    assert VoltageControlEnvironmentSpec.__name__ == "VoltageControlEnvironmentSpec"


def _episodes_differ(a: list[dict], b: list[dict]) -> bool:
    """Return True if any step's controlled_vm_pu/action_mw genuinely differs."""
    return any(
        abs(x["controlled_vm_pu"] - y["controlled_vm_pu"]) > 1e-9
        or abs(x["action_mw"] - y["action_mw"]) > 1e-9
        for x, y in zip(a, b, strict=True)
    )


def test_episodes_differ_helper_is_not_vacuously_true() -> None:
    """False-green guard: identical episodes must NOT be reported as differing.

    This is the check task 3(b) asks for by name: if both policies were
    wired to the same implementation, `_episodes_differ` must say False, not
    True -- otherwise the seam-substitution test below would pass for the
    wrong reason.
    """
    spec = _long_profile_spec()
    episode_a = run_policy_episode(
        spec,
        SensitivityDispatchPolicy(
            sensitivity_pu_per_mw=0.05,
            action_space_mw=spec.der.action_space_mw,
            controlled_bus_id=spec.der.controlled_bus_id,
            voltage_target_pu=spec.voltage_target_pu,
        ),
        step_count=4,
    )
    episode_b = run_policy_episode(
        spec,
        SensitivityDispatchPolicy(
            sensitivity_pu_per_mw=0.05,
            action_space_mw=spec.der.action_space_mw,
            controlled_bus_id=spec.der.controlled_bus_id,
            voltage_target_pu=spec.voltage_target_pu,
        ),
        step_count=4,
    )

    assert episode_a == episode_b
    assert _episodes_differ(episode_a, episode_b) is False


def test_policy_seam_two_registered_policies_yield_different_valid_results() -> None:
    """(b) The policy seam: substituting the policy changes the outcome."""
    spec = _long_profile_spec()
    config = TabularVoltageControlConfig(episode_count=6, step_count=4, random_seed=3)

    trained = train_tabular_voltage_controller(spec, config)
    sensitivity = measure_local_voltage_sensitivity(spec.feeder, spec.der)

    rl_policy = TabularRLPolicy(
        q_table=trained.q_table,
        action_space_mw=spec.der.action_space_mw,
        controlled_bus_id=spec.der.controlled_bus_id,
        config=config,
    )
    sensitivity_policy = SensitivityDispatchPolicy(
        sensitivity_pu_per_mw=sensitivity,
        action_space_mw=spec.der.action_space_mw,
        controlled_bus_id=spec.der.controlled_bus_id,
        voltage_target_pu=spec.voltage_target_pu,
    )

    rl_episode = run_policy_episode(spec, rl_policy, step_count=config.step_count)
    sensitivity_episode = run_policy_episode(
        spec, sensitivity_policy, step_count=config.step_count
    )

    assert len(rl_episode) == config.step_count
    assert len(sensitivity_episode) == config.step_count
    assert all(np.isfinite(r["reward"]) for r in rl_episode)
    assert all(np.isfinite(r["reward"]) for r in sensitivity_episode)
    assert _episodes_differ(rl_episode, sensitivity_episode) is True
