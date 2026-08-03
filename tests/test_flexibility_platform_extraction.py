from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from gridalyn.assets.modeling.thermal import build_thermal_forecast_from_ambient
from gridalyn.operations import (
    build_congestion_forecast,
    prepare_cls_market_replay_context,
    run_cls_capacity_allocation,
    validate_cls_output_consistency,
)
from gridalyn.simulation.simulators.powerflow.topology_cache import (
    validate_building_footprints,
)
from gridalyn.simulation.simulators.powerflow.transformer_validation import (
    TransformerPeakValidationConfig,
    validate_transformer_peak_scenarios,
)


def scenario_label(index: int, ev_percent: int) -> str:
    """Return the canonical EV scenario label used by study reports."""

    return f"S{int(index)}_{int(ev_percent)}pct"


def _mc_frame(values: list[list[float]]) -> pd.DataFrame:
    return pd.DataFrame(
        values,
        columns=[f"realization_{idx}" for idx in range(len(values[0]))],
    )


def test_build_congestion_forecast_returns_project_artifacts_without_io() -> None:
    baseline = _mc_frame(
        [
            [10.0, 10.2, 10.4],
            [11.0, 11.2, 11.4],
            [12.0, 12.2, 12.4],
            [11.0, 11.1, 11.2],
        ]
    )
    ev = _mc_frame(
        [
            [0.0, 0.1, 0.2],
            [0.8, 0.9, 1.0],
            [1.5, 1.6, 1.7],
            [0.6, 0.7, 0.8],
        ]
    )
    forecast = build_thermal_forecast_from_ambient(
        [-10.0, -10.0, -10.0, -10.0],
        resolution_minutes=5,
        s_rated_kva=15_000.0,
        theta_max=110.0,
        start_time="2023-01-01T00:00:00",
    )

    result = build_congestion_forecast(
        baseline_mw=baseline,
        ev_capability_mw=ev,
        ev_percentages=[0, 20, 40],
        p_rated_kw=14_250.0,
        resolution_minutes=5,
        thermal_forecast=forecast,
        target_ev_percent=20,
    )

    assert result.requirements["ev_pct_list"] == [0, 20, 40]
    assert result.requirements["n_realizations"] == 3
    assert len(result.base_peak_values_mw) == 3
    assert len(result.target_peak_values_mw) == 3
    assert list(result.temporal_bounds.columns) == [
        "t_hours",
        "p_limit_trace",
        "base_p5",
        "base_median",
        "base_p95",
        "s2_p5",
        "s2_median",
        "s2_p95",
    ]


def test_run_cls_capacity_allocation_returns_summary_and_dispatch() -> None:
    baseline = _mc_frame([[8.0, 8.1, 8.2], [8.2, 8.3, 8.4], [8.0, 8.1, 8.2]])
    ev = _mc_frame([[0.0, 0.1, 0.2], [0.4, 0.5, 0.6], [0.1, 0.2, 0.3]])
    forecast = build_thermal_forecast_from_ambient(
        [-15.0, -15.0, -15.0],
        resolution_minutes=5,
        s_rated_kva=15_000.0,
        theta_max=110.0,
        start_time="2023-01-01T00:00:00",
    )

    result = run_cls_capacity_allocation(
        baseline_mw=baseline,
        ev_capability_mw=ev,
        ev_percentages=[0, 40],
        thermal_forecast=forecast,
        n_buildings=30,
        n_feeder_blocks=4,
        participation_rate=0.25,
        resolution_minutes=5,
        s_rated_kva=15_000.0,
        p_limit_kw=14_250.0,
        theta_max=110.0,
        market_clearing_interval_h=0.5,
        dispatch_ev_percent=40,
        reference_price_ev_percent=0,
    )

    assert scenario_label(1, 40) in result.summary
    assert result.summary["S1_40pct"]["n_ev"] == 12
    assert set(
        [
            "p_baseline_mean_mw",
            "p_ev_mean_mw",
            "p_soft_cls_mw",
            "p_hard_cls_mw",
            "p_limit_trace_mw",
        ]
    ) <= set(result.dispatch_timeseries.columns)


def test_prepare_cls_market_replay_context_runs_engine_without_project_code() -> None:
    baseline = _mc_frame([[8.0, 8.1, 8.2], [8.2, 8.3, 8.4], [8.0, 8.1, 8.2]])
    ev = _mc_frame([[0.0, 0.1, 0.2], [0.4, 0.5, 0.6], [0.1, 0.2, 0.3]])
    forecast = build_thermal_forecast_from_ambient(
        [-15.0, -15.0, -15.0],
        resolution_minutes=5,
        s_rated_kva=15_000.0,
        theta_max=110.0,
        start_time="2023-01-01T00:00:00",
    )

    context = prepare_cls_market_replay_context(
        baseline_mw=baseline,
        ev_capability_mw=ev,
        thermal_forecast=forecast,
        ev_percent=40.0,
        resolution_minutes=5,
        s_rated_kva=15_000.0,
        p_limit_kw=14_250.0,
        theta_max=110.0,
        n_feeder_blocks=4,
        participation_rate=0.25,
    )
    result = context.run(is_profiled=True)
    _, p_ev_kw, p_total_kw = context.realization_traces("realization_1")

    assert context.ev_scale == 40.0 / 30.0
    assert len(context.p_limit_mw) == 3
    assert "managed_load_kw" in result
    assert p_ev_kw[1] == ev["realization_1"].iloc[1] * 1000.0 * context.ev_scale
    assert p_total_kw[1] > baseline["realization_1"].iloc[1] * 1000.0


def test_validate_cls_output_consistency_checks_cross_artifact_contracts() -> None:
    ev_summary = {
        "S0_0pct": {
            "n_ev": 0,
            "unmanaged_peak_mw": 10.0,
            "total_soft_cls_mwh": 0.0,
            "total_hard_cls_mwh": 0.0,
            "total_rebound_mwh": 0.0,
        },
        "S4_40pct": {
            "n_ev": 4,
            "unmanaged_peak_mw": 12.0,
            "total_soft_cls_mwh": 0.3,
            "total_hard_cls_mwh": 0.1,
            "total_rebound_mwh": 0.05,
        },
        "p_limit_dynamic_mw": 20.0,
        "dynamic_limit_min_mw": 19.0,
        "dynamic_limit_max_mw": 20.0,
    }
    flex = {
        "dynamic_limit_min_mw": 19.0,
        "dynamic_limit_max_mw": 20.0,
        "dynamic_limit_at_peak_mw": 19.5,
        "p_limit_kw": 19_500.0,
    }
    pandapower = {
        "scenarios": [
            {"label": "S0_0pct", "p_peak_mw": 10.0},
            {"label": "S4_40pct", "p_peak_mw": 12.0},
        ]
    }
    dispatch = pd.DataFrame(
        {
            "t_hours": [0.0, 0.5],
            "p_soft_cls_mw": [0.2, 0.4],
            "p_hard_cls_mw": [0.0, 0.2],
            "p_rebound_mw": [0.0, 0.1],
            "p_limit_trace_mw": [19.0, 20.0],
        }
    )
    temporal = pd.DataFrame({"p_limit_trace": [19.0, 20.0]})

    result = validate_cls_output_consistency(
        ev_summary=ev_summary,
        flex_requirements=flex,
        pandapower_validation=pandapower,
        dispatch_timeseries=dispatch,
        temporal_bounds=temporal,
        n_buildings=10,
    )

    assert result.valid is True
    assert result.scenario_labels == ["S0_0pct", "S4_40pct"]
    assert result.s4_soft_cls_mwh == pytest.approx(0.3)
    assert result.s4_hard_cls_mwh == pytest.approx(0.1)


def test_validate_transformer_peak_scenarios_runs_without_project_code() -> None:
    config = TransformerPeakValidationConfig(
        s_rated_mva=1.0,
        s_rated_kva=1000.0,
        theta_max_c=110.0,
        power_factor=0.95,
        hv_voltage_kv=120.0,
        mv_voltage_kv=25.0,
        winter_design_ambient_c=-20.0,
    )

    result = validate_transformer_peak_scenarios(
        scenarios={
            "S0_0pct": {"unmanaged_peak_mw": 0.5},
            "S2_20pct": {"unmanaged_peak_mw": 1.0},
        },
        config=config,
    )

    assert result["transformer"]["p_static_mw"] == pytest.approx(0.95)
    assert result["transformer"]["p_dynamic_mw"] > result["transformer"]["p_static_mw"]
    assert [scenario["ev_pct"] for scenario in result["scenarios"]] == [0, 20]
    assert all(scenario["converged"] for scenario in result["scenarios"])
    assert result["scenarios"][1]["p_peak_mw"] == pytest.approx(1.0)


def test_validate_building_footprints_writes_platform_report(tmp_path: Path) -> None:
    report_path = tmp_path / "footprints_report.json"

    report = validate_building_footprints(
        "examples/tutorials/data/example_buildings.geojson",
        report_path,
    )

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["valid"] is True
    assert payload["counts"]["polygon_footprints"] > 0
    assert payload["source"]["sha256"]
