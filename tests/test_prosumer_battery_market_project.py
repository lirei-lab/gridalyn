import json
from pathlib import Path

import pandas as pd

from gridalyn.projects import project_status, run_workflow, validate_project
from gridalyn.projects.loader import load_project
from gridalyn.projects.runner import plan_stages


PROJECT_ROOT = Path("projects/prosumer_battery_market")


def test_prosumer_battery_market_project_contract_is_valid() -> None:
    report = validate_project(PROJECT_ROOT)

    assert report.valid, report.errors


def test_prosumer_battery_market_workflow_is_small_and_explicit() -> None:
    project = load_project(PROJECT_ROOT / "project.yaml")
    stages = [stage.id for stage in plan_stages(project)]

    assert stages == [
        "prepare_workspace",
        "build_synthetic_feeder",
        "run_realtime_prosumer_market",
    ]


def test_prosumer_battery_market_runs_end_to_end() -> None:
    executed = run_workflow(PROJECT_ROOT)
    status = project_status(PROJECT_ROOT, check_artifacts=True)

    feeder_report = PROJECT_ROOT / "outputs" / "reports" / "synthetic_feeder_report.json"
    market_report = PROJECT_ROOT / "outputs" / "reports" / "prosumer_realtime_market_report.json"
    prosumer_path = PROJECT_ROOT / "outputs" / "data" / "prosumers.csv"
    clearing_path = PROJECT_ROOT / "outputs" / "operations" / "realtime_market_clearing.csv"
    dispatch_path = PROJECT_ROOT / "outputs" / "operations" / "battery_dispatch.csv"
    forecast_path = PROJECT_ROOT / "outputs" / "data" / "realtime_market_forecast.csv"
    offers_path = PROJECT_ROOT / "outputs" / "operations" / "realtime_market_offers.csv"
    voltage_figure = PROJECT_ROOT / "outputs" / "figures" / "synthetic_feeder_voltage_profile.png"
    market_figure = PROJECT_ROOT / "outputs" / "figures" / "prosumer_market_dispatch.png"

    feeder_payload = json.loads(feeder_report.read_text(encoding="utf-8"))
    market_payload = json.loads(market_report.read_text(encoding="utf-8"))
    prosumers = pd.read_csv(prosumer_path)
    clearing = pd.read_csv(clearing_path)
    dispatch = pd.read_csv(dispatch_path)
    forecast = pd.read_csv(forecast_path)
    offers = pd.read_csv(offers_path)

    assert executed == [
        "prepare_workspace",
        "build_synthetic_feeder",
        "run_realtime_prosumer_market",
    ]
    assert status["valid"], status
    assert status["reports"]["ready"], status["reports"]
    assert feeder_payload["summary"]["converged"] is True
    assert feeder_payload["summary"]["bus_count"] == 14
    assert feeder_payload["summary"]["line_count"] == 13
    assert len(prosumers) == 5
    assert len(clearing) == 12
    assert len(forecast) >= 12
    assert set(forecast["lead_interval"]).issuperset({0, 1, 2, 3})
    assert len(offers) >= 12 * 5
    assert dispatch["prosumer_id"].nunique() == 5
    assert market_payload["summary"]["algorithm"] == "rolling_horizon_uniform_price_auction"
    assert market_payload["summary"]["forecast_horizon_intervals"] == 4
    assert market_payload["summary"]["interval_count"] == 12
    assert market_payload["summary"]["prosumer_count"] == 5
    assert market_payload["summary"]["total_cleared_mwh"] > 0.0
    assert market_payload["summary"]["peak_import_before_mw"] > market_payload["summary"]["peak_import_after_mw"]
    accepted = dispatch[dispatch["dispatch_mw"] > 0]
    assert not accepted.empty
    assert (accepted["settlement_price_usd_per_mwh"] == accepted["market_clearing_price_usd_per_mwh"]).all()
    assert voltage_figure.exists()
    assert market_figure.exists()
