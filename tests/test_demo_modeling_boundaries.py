from __future__ import annotations

from pathlib import Path

from gridalyn.projects import (
    load_der_dispatch_assets,
    load_prosumer_assets,
    load_radial_feeder_spec,
    load_voltage_control_der_spec,
)


def test_project_yaml_model_inputs_load_platform_contracts() -> None:
    minimal = load_radial_feeder_spec("projects/minimal_grid_project/project.yaml")
    der_feeder = load_radial_feeder_spec(
        "projects/der_voltage_optimization/project.yaml"
    )
    der_assets = load_der_dispatch_assets(
        "projects/der_voltage_optimization/project.yaml"
    )
    prosumer_feeder = load_radial_feeder_spec(
        "projects/prosumer_battery_market/project.yaml"
    )
    prosumers = load_prosumer_assets("projects/prosumer_battery_market/project.yaml")
    rl_feeder = load_radial_feeder_spec(
        "projects/rl_voltage_control_lightsim/project.yaml"
    )
    rl_der = load_voltage_control_der_spec(
        "projects/rl_voltage_control_lightsim/project.yaml",
        feeder=rl_feeder,
    )

    assert minimal.bus_count == 5
    assert der_feeder.bus_count == 16
    assert len(der_assets) == 5
    assert prosumer_feeder.bus_count == 14
    assert len(prosumers) == 5
    assert rl_der.controlled_bus_id == 9


def test_project_model_inputs_live_in_project_contracts() -> None:
    wrappers = {
        Path("projects/minimal_grid_project/scripts/run_minimal_powerflow.py"): (
            "load_radial_feeder_spec",
            "build_radial_pandapower_feeder",
        ),
        Path("projects/der_voltage_optimization/scripts/network_model.py"): (
            "load_radial_feeder_spec",
            "load_der_dispatch_assets",
        ),
        Path("projects/prosumer_battery_market/scripts/network_model.py"): (
            "load_radial_feeder_spec",
            "load_prosumer_assets",
        ),
        Path("projects/rl_voltage_control_lightsim/scripts/network_model.py"): (
            "load_voltage_control_der_spec",
            "load_numeric_profile_array",
        ),
    }

    forbidden_terms = (
        "demo_specs",
        "demo_cases",
        "_demo_feeder",
        "_demo_environment_spec",
        "RadialFeederSpec(",
        "VoltageControlDERSpec(",
        "DERDispatchAsset(",
        "ProsumerAsset(",
        "PVAsset(",
        "BatteryAsset(",
        "pandapower as pp",
        "pp.runpp",
        "np.array(",
    )
    for path, required_terms in wrappers.items():
        source = path.read_text(encoding="utf-8")
        for term in required_terms:
            assert term in source
        for term in forbidden_terms:
            assert term not in source, f"{path} should keep {term!r} in Gridalyn"


def test_no_project_specific_demo_specs_in_gridalyn_package() -> None:
    assert not Path("gridalyn/assets/modeling/demo_specs.py").exists()
    assert not Path("gridalyn/simulation/demo_cases.py").exists()


def test_advanced_demo_scripts_delegate_modeling_to_gridalyn() -> None:
    checks = {
        Path("projects/der_voltage_optimization/scripts/run_voltage_optimization.py"): (
            "import cvxpy",
            "cp.",
            "pp.create_sgen",
            "pp.create_load",
        ),
        Path("projects/rl_voltage_control_lightsim/scripts/train_rl_agent.py"): (
            "def _train",
            "def _evaluate",
            "def _select_action",
            "q[",
        ),
        Path("projects/ieee_33_bus_demo/scripts/build_ieee33_demo.py"): (
            "pandapower.networks",
            "case33bw",
        ),
        Path("projects/ieee_33_bus_demo/scripts/generate_operational_scenarios.py"): (
            "pandapower.networks",
            "case33bw",
        ),
    }

    for path, forbidden_terms in checks.items():
        source = path.read_text(encoding="utf-8")
        for term in forbidden_terms:
            assert term not in source, f"{path} should delegate {term!r} to Gridalyn"
