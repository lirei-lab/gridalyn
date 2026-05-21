"""Generate deterministic operational scenarios for the IEEE 33-bus demo."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from gridalyn.assets import IEEE_33_BUS_BENCHMARK
from gridalyn.foundation import ReportMetadata, file_reference, write_report
from gridalyn.simulation import (
    StandardPowerflowScenario,
    build_ieee33_benchmark_feeder,
    configure_headless_matplotlib,
    run_standard_powerflow_scenario,
    scenario_to_record,
)


PROJECT_NAME = "ieee_33_bus_demo"


SCENARIOS = (
    StandardPowerflowScenario(
        scenario_id="baseline",
        description="Original IEEE 33-bus feeder.",
    ),
    StandardPowerflowScenario(
        scenario_id="load_growth_20",
        description="Uniform 20 percent demand growth.",
        load_multiplier=1.2,
    ),
    StandardPowerflowScenario(
        scenario_id="pv_midday",
        description="Midday distributed PV at selected downstream buses.",
        pv_buses=(6, 14, 24, 30),
        pv_mw_per_bus=0.25,
    ),
    StandardPowerflowScenario(
        scenario_id="ev_evening_peak",
        description="Evening EV charging demand at selected downstream buses.",
        ev_buses=(17, 18, 25, 30, 32),
        ev_mw_per_bus=0.18,
    ),
    StandardPowerflowScenario(
        scenario_id="pv_plus_ev",
        description="Combined PV and EV condition for a mixed operating case.",
        pv_buses=(6, 14, 24, 30),
        pv_mw_per_bus=0.18,
        ev_buses=(17, 18, 25, 30, 32),
        ev_mw_per_bus=0.12,
    ),
)


def _run_scenario(scenario: StandardPowerflowScenario) -> tuple[dict, pd.DataFrame]:
    return run_standard_powerflow_scenario(
        build_ieee33_benchmark_feeder(),
        scenario,
    )


def _write_scenario_inputs() -> Path:
    path = Path("outputs/data/scenarios.csv")
    rows = [
        scenario_to_record(scenario)
        for scenario in SCENARIOS
    ]
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _write_voltage_comparison(results: pd.DataFrame, voltages: pd.DataFrame) -> Path:
    configure_headless_matplotlib()
    import matplotlib.pyplot as plt

    figure_path = Path("outputs/figures/ieee33_scenario_voltage_comparison.png")
    figure_path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 5.4))
    for scenario_id, group in voltages.groupby("scenario_id", sort=False):
        ax.plot(group["bus_id"], group["vm_pu"], linewidth=1.7, marker="o", markersize=3, label=scenario_id)
    ax.axhline(0.95, color="#c0392b", linestyle="--", linewidth=1.2, label="0.95 p.u.")
    ax.set_title("IEEE 33-Bus Demo - Scenario Voltage Comparison")
    ax.set_xlabel("Bus index")
    ax.set_ylabel("Voltage magnitude [p.u.]")
    ax.grid(True, alpha=0.32)
    ax.legend(loc="lower left", ncol=2, fontsize=8)
    fig.tight_layout()
    fig.savefig(figure_path, dpi=160)
    plt.close(fig)
    return figure_path


def _summary(results: pd.DataFrame) -> dict:
    best = results.sort_values(["min_voltage_pu", "line_loss_mw"], ascending=[False, True]).iloc[0]
    worst = results.sort_values(["min_voltage_pu", "line_loss_mw"], ascending=[True, False]).iloc[0]
    return {
        "scenario_count": int(len(results)),
        "scenario_ids": list(results["scenario_id"]),
        "best_voltage_scenario": str(best["scenario_id"]),
        "worst_voltage_scenario": str(worst["scenario_id"]),
        "min_voltage_pu": float(results["min_voltage_pu"].min()),
        "max_voltage_pu": float(results["max_voltage_pu"].max()),
        "max_line_loading_percent": float(results["max_line_loading_percent"].max()),
        "max_voltage_violation_count": int(results["voltage_violation_count"].max()),
    }


def main() -> int:
    scenario_input_path = _write_scenario_inputs()
    rows = []
    voltage_frames = []
    for scenario in SCENARIOS:
        result, voltage = _run_scenario(scenario)
        rows.append(result)
        voltage_frames.append(voltage)

    results = pd.DataFrame(rows)
    voltages = pd.concat(voltage_frames, ignore_index=True)
    result_path = Path("outputs/data/scenario_results.csv")
    voltage_path = Path("outputs/data/scenario_voltage_profiles.csv")
    results.to_csv(result_path, index=False)
    voltages.to_csv(voltage_path, index=False)
    figure_path = _write_voltage_comparison(results, voltages)
    report_path = Path("outputs/reports/ieee33_scenario_comparison_report.json")

    write_report(
        report_path,
        metadata=ReportMetadata(
            report_id="ieee33_scenario_comparison_report",
            source_domain=PROJECT_NAME,
            project={"name": PROJECT_NAME},
        ),
        inputs=[
            file_reference(scenario_input_path),
            {"name": IEEE_33_BUS_BENCHMARK.source_name, "type": "gridalyn_benchmark_feeder"},
        ],
        artifacts=[
            file_reference(result_path),
            file_reference(voltage_path),
            file_reference(figure_path),
        ],
        summary=_summary(results),
        validation={
            "valid": bool(results["converged"].all()),
            "errors": [] if bool(results["converged"].all()) else ["one or more scenarios did not converge"],
            "warnings": [],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
