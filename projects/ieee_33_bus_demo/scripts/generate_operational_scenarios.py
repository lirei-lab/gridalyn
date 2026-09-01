"""Run the operational scenarios declared in project.yaml for the IEEE 33-bus demo."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from gridalyn.assets import IEEE_33_BUS_BENCHMARK
from gridalyn.projects.model_inputs import load_standard_powerflow_scenarios
from gridalyn.projects.scripting import ProjectScript, project_script
from gridalyn.simulation import (
    StandardPowerflowScenario,
    build_ieee33_benchmark_feeder,
    run_standard_powerflow_scenario,
    scenario_to_record,
)


def _run_scenario(scenario: StandardPowerflowScenario) -> tuple[dict, pd.DataFrame]:
    return run_standard_powerflow_scenario(
        build_ieee33_benchmark_feeder(),
        scenario,
    )


def _write_scenario_inputs(
    script: ProjectScript,
    scenarios: tuple[StandardPowerflowScenario, ...],
) -> Path:
    path = script.data_dir / "scenarios.csv"
    rows = [scenario_to_record(scenario) for scenario in scenarios]
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


def _write_voltage_comparison(script: ProjectScript, voltages: pd.DataFrame) -> Path:
    import matplotlib.pyplot as plt

    figure_path = script.figures_dir / "ieee33_scenario_voltage_comparison.png"
    fig, ax = plt.subplots(figsize=(10, 5.4))
    for scenario_id, group in voltages.groupby("scenario_id", sort=False):
        ax.plot(
            group["bus_id"],
            group["vm_pu"],
            linewidth=1.7,
            marker="o",
            markersize=3,
            label=scenario_id,
        )
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
    best = results.sort_values(
        ["min_voltage_pu", "line_loss_mw"], ascending=[False, True]
    ).iloc[0]
    worst = results.sort_values(
        ["min_voltage_pu", "line_loss_mw"], ascending=[True, False]
    ).iloc[0]
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
    script = project_script()
    scenarios = load_standard_powerflow_scenarios(script.project)
    scenario_input_path = _write_scenario_inputs(script, scenarios)
    rows = []
    voltage_frames = []
    for scenario in scenarios:
        result, voltage = _run_scenario(scenario)
        rows.append(result)
        voltage_frames.append(voltage)

    results = pd.DataFrame(rows)
    voltages = pd.concat(voltage_frames, ignore_index=True)
    result_path = script.data_dir / "scenario_results.csv"
    voltage_path = script.data_dir / "scenario_voltage_profiles.csv"
    results.to_csv(result_path, index=False)
    voltages.to_csv(voltage_path, index=False)
    figure_path = _write_voltage_comparison(script, voltages)

    script.write_report(
        "ieee33_scenario_comparison_report",
        inputs=[
            script.file_reference(scenario_input_path),
            {
                "name": IEEE_33_BUS_BENCHMARK.source_name,
                "type": "gridalyn_benchmark_feeder",
            },
        ],
        artifacts=[
            script.file_reference(result_path),
            script.file_reference(voltage_path),
            script.file_reference(figure_path),
        ],
        summary=_summary(results),
        validation={
            "valid": bool(results["converged"].all()),
            "errors": (
                []
                if bool(results["converged"].all())
                else ["one or more scenarios did not converge"]
            ),
            "warnings": [],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
