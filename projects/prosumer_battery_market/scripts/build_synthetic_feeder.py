"""Build the synthetic feeder, base power-flow report, and prosumer registry."""

from __future__ import annotations

from pathlib import Path

from gridalyn.assets import prosumer_assets_to_frame
from gridalyn.projects.scripting import ProjectScript, project_script
from gridalyn.simulation import (
    StandardPowerflowScenario,
    run_standard_powerflow_scenario,
    write_pandapower_element_tables,
    write_powerflow_report,
    write_voltage_profile_figure,
)

from network_model import PROSUMER_ASSETS, build_synthetic_feeder


def _write_tables(script: ProjectScript, net) -> dict[str, Path]:
    tables = write_pandapower_element_tables(net, script.data_dir)
    prosumer_path = script.data_dir / "prosumers.csv"
    prosumer_assets_to_frame(PROSUMER_ASSETS).to_csv(prosumer_path, index=False)
    return {**tables, "prosumers": prosumer_path}


def main() -> int:
    script = project_script()
    net = build_synthetic_feeder()
    run_standard_powerflow_scenario(
        net,
        StandardPowerflowScenario(
            scenario_id="baseline",
            description="Canonical prosumer feeder baseline.",
        ),
    )
    tables = _write_tables(script, net)
    figure_path = write_voltage_profile_figure(
        net,
        script.figures_dir / "synthetic_feeder_voltage_profile.png",
        title="Synthetic 14-Bus Feeder - Baseline Voltage",
    )

    write_powerflow_report(
        script.reports_dir / "synthetic_feeder_report.json",
        metadata=script.report_metadata("synthetic_feeder_report"),
        net=net,
        inputs=[
            {
                "name": "synthetic_14_bus_radial_feeder",
                "type": "deterministic_project_generator",
            }
        ],
        artifacts=[
            script.file_reference(path)
            for path in (
                tables["buses"],
                tables["lines"],
                tables["loads"],
                tables["prosumers"],
                figure_path,
            )
        ],
        summary={"network": "synthetic_14_bus_radial_feeder", "prosumer_count": int(len(PROSUMER_ASSETS))},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
