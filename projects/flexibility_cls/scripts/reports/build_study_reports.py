"""Build canonical reports from Flexibility CLS project outputs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.interfaces.reporting.schemas import (
    canonical_report,
    load_json,
    relpath,
    write_json,
    write_report,
)


def _scenario_items(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {key: value for key, value in summary.items() if isinstance(value, dict)}


def _dispatch_metrics(dispatch_path: Path) -> dict[str, Any]:
    if not dispatch_path.exists():
        return {}
    dispatch = pd.read_parquet(dispatch_path)
    if len(dispatch) < 2 or "t_hours" not in dispatch:
        return {"n_timesteps": int(len(dispatch))}
    dt_h = float(dispatch["t_hours"].iloc[1] - dispatch["t_hours"].iloc[0])
    metrics = {"n_timesteps": int(len(dispatch)), "resolution_hours": dt_h}
    for column, key in (
        ("p_soft_cls_mw", "soft_cls_mwh"),
        ("p_hard_cls_mw", "hard_cls_mwh"),
        ("p_rebound_mw", "rebound_mwh"),
    ):
        if column in dispatch:
            metrics[key] = float(dispatch[column].sum() * dt_h)
    if "p_limit_trace_mw" in dispatch:
        metrics["dynamic_limit_min_mw"] = float(dispatch["p_limit_trace_mw"].min())
        metrics["dynamic_limit_max_mw"] = float(dispatch["p_limit_trace_mw"].max())
    return metrics


def build_study_reports(
    *,
    root: Path = ROOT,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    output_root = root / "projects" / "flexibility_cls" / "outputs"
    out_dir = (out_dir or (output_root / "reports")).resolve()
    json_dir = output_root / "json"
    data_dir = output_root / "data"

    ev_summary_path = json_dir / "ev_summary_results.json"
    flex_path = json_dir / "flex_requirements.json"
    pandapower_path = json_dir / "pandapower_validation.json"
    spatial_path = json_dir / "spatial_cls_powerflow_validation.json"
    dispatch_path = data_dir / "market_dispatch_timeseries.parquet"
    provider_shadow_path = out_dir / "provider_selection_shadow_report.json"
    network_impact_path = out_dir / "network_impact_verification_report.json"
    operational_kpi_path = out_dir / "operational_kpi_report.json"
    operation_run_path = output_root / "operations" / "operation_run.json"

    ev_summary = load_json(ev_summary_path)
    scenarios = _scenario_items(ev_summary)
    flex = load_json(flex_path)
    pandapower = load_json(pandapower_path) if pandapower_path.exists() else {}
    spatial = load_json(spatial_path) if spatial_path.exists() else {}
    provider_shadow = load_json(provider_shadow_path) if provider_shadow_path.exists() else {}
    network_impact = load_json(network_impact_path) if network_impact_path.exists() else {}
    operational_kpi = load_json(operational_kpi_path) if operational_kpi_path.exists() else {}
    operation_run = load_json(operation_run_path) if operation_run_path.exists() else {}

    report_paths: dict[str, str] = {}

    stage1_metrics = {
        "scenario_count": int(len(scenarios)),
        "scenarios": scenarios,
        "dynamic_limit_mw": {
            "min": ev_summary.get("dynamic_limit_min_mw"),
            "mean": ev_summary.get("dynamic_limit_mean_mw"),
            "max": ev_summary.get("dynamic_limit_max_mw"),
        },
    }
    stage1 = canonical_report(
        report_id="stage_1_stochastic_load",
        title="Stage 1 Stochastic Load and EV Adoption",
        root=root,
        inputs=[ev_summary_path],
        metrics=stage1_metrics,
        artifacts={
            "ev_summary_results": relpath(ev_summary_path, root),
            "stage_1_figures": "projects/flexibility_cls/outputs/figures/02_stage1_stochastic_load",
        },
        stage="stage_1",
        source_domain="flexibility_cls",
        project_name="flexibility_cls",
    )
    report_paths["stage_1_stochastic_load"] = write_report(out_dir / "stage_1_stochastic_load_report.json", stage1, root=root)

    stage2 = canonical_report(
        report_id="stage_2_thermal_forecast",
        title="Stage 2 Dynamic Thermal Forecast and Flexibility Requirement",
        root=root,
        inputs=[flex_path],
        metrics={
            "target_flexibility_mw": flex.get("D_tar_mw"),
            "dynamic_limit_mw": {
                "min": flex.get("dynamic_limit_min_mw"),
                "mean": flex.get("dynamic_limit_mean_mw"),
                "max": flex.get("dynamic_limit_max_mw"),
                "at_peak": flex.get("dynamic_limit_at_peak_mw"),
            },
            "thermal_model": ev_summary.get("thermal_model") or flex.get("thermal_model"),
            "prob_limit": flex.get("prob_limit"),
            "ev_pct_list": flex.get("ev_pct_list"),
        },
        artifacts={
            "flex_requirements": relpath(flex_path, root),
            "stage_2_figures": "projects/flexibility_cls/outputs/figures/03_stage2_thermal_screening",
        },
        stage="stage_2",
        source_domain="flexibility_cls",
        project_name="flexibility_cls",
    )
    report_paths["stage_2_thermal_forecast"] = write_report(out_dir / "stage_2_thermal_forecast_report.json", stage2, root=root)

    stage3 = canonical_report(
        report_id="stage_3_market_clearing",
        title="Stage 3 Day-Ahead Market Clearing",
        root=root,
        inputs=[ev_summary_path, dispatch_path],
        metrics={
            "scenarios": {
                scenario_id: {
                    "soft_cls_mw": values.get("soft_cls_mw"),
                    "hard_cls_mw": values.get("hard_cls_mw"),
                    "max_auction_clearing_price": values.get("max_auction_clearing_price"),
                    "total_market_settlement_usd": values.get("total_market_settlement_usd"),
                    "total_market_penalties_usd": values.get("total_market_penalties_usd"),
                }
                for scenario_id, values in scenarios.items()
            },
            "dispatch_timeseries": _dispatch_metrics(dispatch_path),
        },
        artifacts={
            "market_dispatch_timeseries": relpath(dispatch_path, root) if dispatch_path.exists() else None,
            "stage_3_figures": "projects/flexibility_cls/outputs/figures/04_stage3_market_clearing",
        },
        stage="stage_3",
        source_domain="flexibility_cls",
        project_name="flexibility_cls",
    )
    report_paths["stage_3_market_clearing"] = write_report(out_dir / "stage_3_market_clearing_report.json", stage3, root=root)

    stage4 = canonical_report(
        report_id="stage_4_realtime_dispatch",
        title="Stage 4 Realtime CLS Dispatch and Spatial Powerflow",
        root=root,
        inputs=[
            ev_summary_path,
            dispatch_path,
            spatial_path,
            provider_shadow_path,
            network_impact_path,
            operational_kpi_path,
        ],
        metrics={
            "s4_summary": scenarios.get("S4_40pct", {}),
            "dispatch_timeseries": _dispatch_metrics(dispatch_path),
            "spatial_cls": spatial,
            "provider_selection_shadow": provider_shadow.get("summary", {}),
            "operational_kpis": operational_kpi.get("summary", {}),
            "operation_run": {
                "operation_id": operation_run.get("operation_id"),
                "operation_type": operation_run.get("operation_type"),
                "status": operation_run.get("status"),
            },
            "network_impact_verification": {
                "comparisons": network_impact.get("comparisons", {}),
                "dispatch": network_impact.get("dispatch", {}),
                "constraints": network_impact.get("constraint_ids", []),
            },
        },
        artifacts={
            "spatial_cls_powerflow_validation": relpath(spatial_path, root) if spatial_path.exists() else None,
            "provider_selection_shadow_report": relpath(provider_shadow_path, root)
            if provider_shadow_path.exists()
            else None,
            "network_impact_verification_report": relpath(network_impact_path, root)
            if network_impact_path.exists()
            else None,
            "operational_kpi_report": relpath(operational_kpi_path, root)
            if operational_kpi_path.exists()
            else None,
            "operation_run": relpath(operation_run_path, root)
            if operation_run_path.exists()
            else None,
            "stage_4_figures": "projects/flexibility_cls/outputs/figures/05_stage4_realtime_dispatch",
        },
        stage="stage_4",
        source_domain="flexibility_cls",
        project_name="flexibility_cls",
    )
    report_paths["stage_4_realtime_dispatch"] = write_report(out_dir / "stage_4_realtime_dispatch_report.json", stage4, root=root)
    if provider_shadow_path.exists():
        report_paths["provider_selection_shadow"] = relpath(provider_shadow_path, root)
    if network_impact_path.exists():
        report_paths["network_impact_verification"] = relpath(network_impact_path, root)
    if operational_kpi_path.exists():
        report_paths["operational_kpi"] = relpath(operational_kpi_path, root)
    if operation_run_path.exists():
        report_paths["operation_run"] = relpath(operation_run_path, root)

    stage5 = canonical_report(
        report_id="stage_5_settlement",
        title="Stage 5 Settlement and Economic Efficiency",
        root=root,
        inputs=[ev_summary_path],
        metrics={
            "total_market_settlement_usd": {
                scenario_id: values.get("total_market_settlement_usd")
                for scenario_id, values in scenarios.items()
            },
            "total_market_penalties_usd": {
                scenario_id: values.get("total_market_penalties_usd")
                for scenario_id, values in scenarios.items()
            },
        },
        artifacts={
            "economic_efficiency_results": "projects/flexibility_cls/outputs/economic_efficiency_results.txt",
            "stage_5_figures": "projects/flexibility_cls/outputs/figures/06_stage5_settlement",
        },
        stage="stage_5",
        source_domain="flexibility_cls",
        project_name="flexibility_cls",
    )
    report_paths["stage_5_settlement"] = write_report(out_dir / "stage_5_settlement_report.json", stage5, root=root)

    consistency = canonical_report(
        report_id="output_consistency",
        title="Flexibility CLS Study Output Consistency Inputs",
        root=root,
        inputs=[ev_summary_path, flex_path, pandapower_path, dispatch_path],
        metrics={
            "scenario_labels": sorted(scenarios.keys()),
            "pandapower_scenario_count": len(pandapower.get("scenarios", [])),
        },
        artifacts={"consistency_script": "projects/flexibility_cls/scripts/pipeline/verify_output_consistency.py"},
        stage="validation",
        source_domain="flexibility_cls",
        project_name="flexibility_cls",
    )
    report_paths["output_consistency"] = write_report(out_dir / "output_consistency_report.json", consistency, root=root)

    figure_groups = {
            "stage_1": "projects/flexibility_cls/outputs/figures/02_stage1_stochastic_load",
            "stage_2": "projects/flexibility_cls/outputs/figures/03_stage2_thermal_screening",
            "stage_3": "projects/flexibility_cls/outputs/figures/04_stage3_market_clearing",
            "stage_4": "projects/flexibility_cls/outputs/figures/05_stage4_realtime_dispatch",
            "stage_5": "projects/flexibility_cls/outputs/figures/06_stage5_settlement",
    }
    manifest = canonical_report(
        report_id="study_run_manifest",
        title="Flexibility CLS Study Run Manifest",
        root=root,
        inputs=[],
        metrics={
            "reports": report_paths,
            "report_count": len(report_paths),
            "figure_groups": figure_groups,
        },
        artifacts={
            **{f"report:{name}": path for name, path in report_paths.items()},
            **{f"figures:{name}": path for name, path in figure_groups.items()},
        },
        stage="manifest",
        source_domain="flexibility_cls",
        project_name="flexibility_cls",
    )
    write_json(out_dir / "study_run_manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build canonical Flexibility CLS Study reports.")
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()
    manifest = build_study_reports(root=ROOT, out_dir=args.out_dir)
    print(
        "Built Flexibility CLS project canonical reports: "
        f"{manifest['summary']['report_count']} reports"
    )


if __name__ == "__main__":
    main()
