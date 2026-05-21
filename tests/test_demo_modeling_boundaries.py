from __future__ import annotations

from pathlib import Path


def test_demo_network_models_use_gridalyn_feeder_contracts() -> None:
    for path in (
        Path("projects/der_voltage_optimization/scripts/network_model.py"),
        Path("projects/prosumer_battery_market/scripts/network_model.py"),
        Path("projects/rl_voltage_control_lightsim/scripts/network_model.py"),
    ):
        source = path.read_text(encoding="utf-8")
        assert "RadialFeederSpec" in source
        assert "create_empty_network" not in source
        assert "create_line_from_parameters" not in source


def test_advanced_demo_scripts_delegate_modeling_to_gridalyn() -> None:
    checks = {
        Path("projects/der_voltage_optimization/scripts/solve_voltage_optimization.py"): (
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
