import json
from pathlib import Path

from gridalyn.projects import project_status, run_workflow, validate_project
from gridalyn.projects.loader import load_project
from gridalyn.projects.runner import plan_stages


PROJECT_ROOT = Path("projects/ieee_33_bus_demo")


def test_ieee_33_demo_project_contract_is_valid() -> None:
    report = validate_project(PROJECT_ROOT)

    assert report.valid, report.errors


def test_ieee_33_demo_workflow_is_small_and_explicit() -> None:
    project = load_project(PROJECT_ROOT / "project.yaml")
    stages = [stage.id for stage in plan_stages(project)]

    assert stages == [
        "prepare_workspace",
        "run_ieee33_powerflow",
        "generate_operational_scenarios",
        "run_daily_timeseries",
    ]


def test_ieee_33_demo_runs_and_writes_expected_artifacts() -> None:
    executed = run_workflow(PROJECT_ROOT)
    status = project_status(PROJECT_ROOT, check_artifacts=True)
    report_path = PROJECT_ROOT / "outputs" / "reports" / "ieee33_powerflow_report.json"
    scenario_report_path = (
        PROJECT_ROOT / "outputs" / "reports" / "ieee33_scenario_comparison_report.json"
    )
    scenarios_path = PROJECT_ROOT / "outputs" / "data" / "scenario_results.csv"
    figure_path = PROJECT_ROOT / "outputs" / "figures" / "ieee33_voltage_profile.png"
    scenario_figure_path = (
        PROJECT_ROOT / "outputs" / "figures" / "ieee33_scenario_voltage_comparison.png"
    )
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    scenario_payload = json.loads(scenario_report_path.read_text(encoding="utf-8"))
    summary = payload["summary"]
    scenario_summary = scenario_payload["summary"]

    assert executed == [
        "prepare_workspace",
        "run_ieee33_powerflow",
        "generate_operational_scenarios",
        "run_daily_timeseries",
    ]
    assert status["valid"], status
    assert status["reports"]["ready"], status["reports"]
    assert figure_path.exists()
    assert scenario_figure_path.exists()
    assert scenarios_path.exists()
    assert summary["converged"] is True
    assert summary["bus_count"] == 33
    assert summary["line_count"] == 37
    assert summary["load_count"] == 32
    assert summary["min_voltage_pu"] < 1.0
    assert scenario_summary["scenario_count"] == 5
    assert scenario_summary["best_voltage_scenario"] == "pv_midday"
    assert scenario_summary["worst_voltage_scenario"] == "ev_evening_peak"
