import json
from pathlib import Path

import pandas as pd

from gridalyn.projects import project_status, run_workflow, validate_project
from gridalyn.projects.loader import load_project
from gridalyn.projects.runner import plan_stages


PROJECT_ROOT = Path("projects/der_voltage_optimization")


def test_der_voltage_optimization_project_contract_is_valid() -> None:
    report = validate_project(PROJECT_ROOT)

    assert report.valid, report.errors


def test_der_voltage_optimization_workflow_is_small_and_explicit() -> None:
    project = load_project(PROJECT_ROOT / "project.yaml")
    stages = [stage.id for stage in plan_stages(project)]

    assert stages == [
        "prepare_workspace",
        "build_der_feeder",
        "solve_voltage_optimization",
    ]


def test_der_voltage_optimization_runs_and_verifies_pandapower() -> None:
    executed = run_workflow(PROJECT_ROOT)
    status = project_status(PROJECT_ROOT, check_artifacts=True)

    feeder_report = PROJECT_ROOT / "outputs" / "reports" / "der_feeder_report.json"
    optimization_report = PROJECT_ROOT / "outputs" / "reports" / "der_voltage_optimization_report.json"
    der_assets_path = PROJECT_ROOT / "outputs" / "data" / "der_assets.csv"
    sensitivity_path = PROJECT_ROOT / "outputs" / "data" / "voltage_sensitivity_matrix.csv"
    dispatch_path = PROJECT_ROOT / "outputs" / "operations" / "der_dispatch.csv"
    verification_path = PROJECT_ROOT / "outputs" / "data" / "pandapower_verification.csv"
    figure_path = PROJECT_ROOT / "outputs" / "figures" / "der_voltage_optimization.png"

    feeder = json.loads(feeder_report.read_text(encoding="utf-8"))
    optimization = json.loads(optimization_report.read_text(encoding="utf-8"))
    der_assets = pd.read_csv(der_assets_path)
    sensitivity = pd.read_csv(sensitivity_path)
    dispatch = pd.read_csv(dispatch_path)
    verification = pd.read_csv(verification_path)

    assert executed == [
        "prepare_workspace",
        "build_der_feeder",
        "solve_voltage_optimization",
    ]
    assert status["valid"], status
    assert status["reports"]["ready"], status["reports"]
    assert feeder["summary"]["converged"] is True
    assert feeder["summary"]["bus_count"] == 16
    assert len(der_assets) == 5
    assert sensitivity.shape[0] >= 5
    assert len(dispatch) == 5
    assert optimization["summary"]["algorithm"] == "cvxpy_linearized_voltage_constrained_der_dispatch"
    assert optimization["summary"]["solver_status"] in {"optimal", "optimal_inaccurate"}
    assert optimization["summary"]["verified_max_voltage_after_pu"] <= 1.051
    assert optimization["summary"]["verified_max_voltage_before_pu"] > optimization["summary"]["verified_max_voltage_after_pu"]
    assert optimization["summary"]["total_pv_curtailment_mw"] > 0.0
    assert verification["optimized_vm_pu"].max() <= 1.051
    assert figure_path.exists()
