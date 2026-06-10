"""Build reports and figures for the IEEE 33-bus demo project."""

from __future__ import annotations

from gridalyn.assets import IEEE_33_BUS_BENCHMARK
from gridalyn.projects.scripting import project_script
from gridalyn.simulation import (
    build_ieee33_benchmark_feeder,
    write_pandapower_element_tables,
    write_powerflow_report,
    write_voltage_profile_figure,
)


def main() -> int:
    script = project_script()
    net = build_ieee33_benchmark_feeder(run_powerflow=True)
    tables = write_pandapower_element_tables(net, script.data_dir)
    figure = write_voltage_profile_figure(
        net,
        script.figures_dir / "ieee33_voltage_profile.png",
        title="IEEE 33-Bus Demo - Voltage Profile",
        xlabel="Bus index",
        figsize=(9.0, 4.8),
    )
    write_powerflow_report(
        script.reports_dir / "ieee33_powerflow_report.json",
        metadata=script.report_metadata("ieee33_powerflow_report"),
        net=net,
        inputs=[
            {
                "name": IEEE_33_BUS_BENCHMARK.source_name,
                "type": "gridalyn_benchmark_feeder",
            }
        ],
        artifacts=[
            script.file_reference(path)
            for path in (tables["buses"], tables["lines"], tables["loads"], figure)
        ],
        summary={"network": IEEE_33_BUS_BENCHMARK.benchmark_id},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
