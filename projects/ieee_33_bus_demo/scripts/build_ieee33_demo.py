"""Build reports and figures for the IEEE 33-bus demo project."""

from __future__ import annotations

from pathlib import Path

from gridalyn.assets import IEEE_33_BUS_BENCHMARK
from gridalyn.foundation import ReportMetadata
from gridalyn.simulation import (
    build_ieee33_benchmark_feeder,
    write_pandapower_element_tables,
    write_powerflow_report,
    write_voltage_profile_figure,
)


PROJECT_NAME = "ieee_33_bus_demo"


def main() -> int:
    net = build_ieee33_benchmark_feeder(run_powerflow=True)
    tables = write_pandapower_element_tables(net, "outputs/data")
    figure = write_voltage_profile_figure(
        net,
        "outputs/figures/ieee33_voltage_profile.png",
        title="IEEE 33-Bus Demo - Voltage Profile",
        xlabel="Bus index",
        figsize=(9.0, 4.8),
    )
    report_path = Path("outputs/reports/ieee33_powerflow_report.json")

    write_powerflow_report(
        report_path,
        metadata=ReportMetadata(
            report_id="ieee33_powerflow_report",
            source_domain=PROJECT_NAME,
            project={"name": PROJECT_NAME},
        ),
        net=net,
        inputs=[
            {
                "name": IEEE_33_BUS_BENCHMARK.source_name,
                "type": "gridalyn_benchmark_feeder",
            }
        ],
        artifacts=[tables["buses"], tables["lines"], tables["loads"], figure],
        summary={"network": IEEE_33_BUS_BENCHMARK.benchmark_id},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
