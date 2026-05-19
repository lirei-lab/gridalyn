import json
from pathlib import Path

import pandas as pd

from gridalyn.platform import project_status, run_workflow, validate_project
from gridalyn.projects.loader import load_project
from gridalyn.projects.runner import plan_stages


MINIMAL_PROJECT = Path("projects/minimal_grid_project")
GEOJSON_PROJECT = Path("projects/synthetic_geojson_feeder")


def test_minimal_grid_project_contract_and_workflow_are_explicit() -> None:
    report = validate_project(MINIMAL_PROJECT)
    project = load_project(MINIMAL_PROJECT / "project.yaml")
    stages = [stage.id for stage in plan_stages(project)]

    assert report.valid, report.errors
    assert stages == [
        "prepare_workspace",
        "run_minimal_powerflow",
    ]


def test_minimal_grid_project_runs_end_to_end() -> None:
    executed = run_workflow(MINIMAL_PROJECT)
    status = project_status(MINIMAL_PROJECT, check_artifacts=True)

    report_path = MINIMAL_PROJECT / "outputs" / "reports" / "minimal_grid_report.json"
    buses_path = MINIMAL_PROJECT / "outputs" / "data" / "buses.csv"
    lines_path = MINIMAL_PROJECT / "outputs" / "data" / "lines.csv"
    loads_path = MINIMAL_PROJECT / "outputs" / "data" / "loads.csv"
    figure_path = MINIMAL_PROJECT / "outputs" / "figures" / "minimal_voltage_profile.png"

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    buses = pd.read_csv(buses_path)
    lines = pd.read_csv(lines_path)
    loads = pd.read_csv(loads_path)

    assert executed == ["prepare_workspace", "run_minimal_powerflow"]
    assert status["valid"], status
    assert status["reports"]["ready"], status["reports"]
    assert payload["summary"]["project_intent"] == "minimal_grid_hello_world"
    assert payload["summary"]["bus_count"] == 5
    assert payload["summary"]["line_count"] == 4
    assert payload["summary"]["load_count"] == 4
    assert payload["summary"]["powerflow_converged"] is True
    assert payload["summary"]["min_voltage_pu"] > 0.98
    assert len(buses) == 5
    assert len(lines) == 4
    assert len(loads) == 4
    assert figure_path.exists()


def test_synthetic_geojson_feeder_contract_and_workflow_are_explicit() -> None:
    report = validate_project(GEOJSON_PROJECT)
    project = load_project(GEOJSON_PROJECT / "project.yaml")
    stages = [stage.id for stage in plan_stages(project)]

    assert report.valid, report.errors
    assert stages == [
        "prepare_workspace",
        "generate_building_footprints",
        "build_synthetic_feeder",
    ]


def test_synthetic_geojson_feeder_runs_end_to_end() -> None:
    executed = run_workflow(GEOJSON_PROJECT)
    status = project_status(GEOJSON_PROJECT, check_artifacts=True)

    geojson_path = GEOJSON_PROJECT / "outputs" / "data" / "building_footprints.geojson"
    report_path = GEOJSON_PROJECT / "outputs" / "reports" / "synthetic_geojson_feeder_report.json"
    validation_path = GEOJSON_PROJECT / "outputs" / "reports" / "synthetic_network_validation_report.json"
    buses_path = GEOJSON_PROJECT / "outputs" / "data" / "buses.csv"
    lines_path = GEOJSON_PROJECT / "outputs" / "data" / "lines.csv"
    loads_path = GEOJSON_PROJECT / "outputs" / "data" / "loads.csv"
    figure_path = GEOJSON_PROJECT / "outputs" / "figures" / "synthetic_feeder_topology.png"

    geojson = json.loads(geojson_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    validation = json.loads(validation_path.read_text(encoding="utf-8"))
    buses = pd.read_csv(buses_path)
    lines = pd.read_csv(lines_path)
    loads = pd.read_csv(loads_path)

    assert executed == [
        "prepare_workspace",
        "generate_building_footprints",
        "build_synthetic_feeder",
    ]
    assert status["valid"], status
    assert status["reports"]["ready"], status["reports"]
    assert geojson["type"] == "FeatureCollection"
    assert len(geojson["features"]) == 9
    assert report["summary"]["project_intent"] == "geojson_to_synthetic_feeder"
    assert report["summary"]["building_count"] == 9
    assert report["summary"]["pandapower_bus_count"] >= 9
    assert report["summary"]["powerflow_converged"] is True
    assert validation["valid"] is True
    assert not buses.empty
    assert not lines.empty
    assert not loads.empty
    assert figure_path.exists()
