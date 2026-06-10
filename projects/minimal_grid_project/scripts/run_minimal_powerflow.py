"""Run the canonical minimal Gridalyn feeder and write project artifacts."""

from __future__ import annotations

from gridalyn.projects.scripting import project_script
from gridalyn.simulation import (
    StandardPowerflowScenario,
    build_radial_pandapower_feeder,
    run_standard_powerflow_scenario,
    write_pandapower_element_tables,
    write_powerflow_report,
    write_voltage_profile_figure,
)


def main() -> int:
    script = project_script()
    feeder = script.load_radial_feeder_spec()
    net = build_radial_pandapower_feeder(feeder)
    run_standard_powerflow_scenario(
        net,
        StandardPowerflowScenario(
            scenario_id="baseline",
            description="Canonical five-bus teaching feeder.",
        ),
    )
    tables = write_pandapower_element_tables(net, script.data_dir)
    figure_path = write_voltage_profile_figure(
        net,
        script.figures_dir / "minimal_voltage_profile.png",
        title="Minimal Feeder Voltage Profile",
        figsize=(7.0, 4.2),
    )
    write_powerflow_report(
        script.reports_dir / "minimal_grid_report.json",
        metadata=script.report_metadata("minimal_grid_report"),
        net=net,
        artifacts=[script.file_reference(path) for path in (*tables.values(), figure_path)],
        summary={
            "project_intent": "minimal_grid_hello_world",
            "powerflow_converged": bool(net.converged),
            "max_line_loading_pct": float(net.res_line.loading_percent.max()),
        },
        validation={"valid": bool(net.converged), "errors": [], "warnings": []},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
