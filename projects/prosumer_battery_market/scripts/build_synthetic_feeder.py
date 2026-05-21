"""Build the synthetic feeder, base power-flow report, and prosumer registry."""

from __future__ import annotations

from pathlib import Path

import pandapower as pp

from gridalyn.assets import prosumer_assets_to_frame
from gridalyn.foundation import ReportMetadata
from gridalyn.simulation import (
    write_pandapower_element_tables,
    write_powerflow_report,
    write_voltage_profile_figure,
)

from network_model import PROSUMER_ASSETS, build_synthetic_feeder


PROJECT_NAME = "prosumer_battery_market"


def _write_tables(net: pp.pandapowerNet) -> dict[str, Path]:
    tables = write_pandapower_element_tables(net, "outputs/data")
    prosumer_path = Path("outputs/data/prosumers.csv")
    prosumer_path.parent.mkdir(parents=True, exist_ok=True)
    prosumer_assets_to_frame(PROSUMER_ASSETS).to_csv(prosumer_path, index=False)
    return {**tables, "prosumers": prosumer_path}


def main() -> int:
    net = build_synthetic_feeder()
    pp.runpp(net, algorithm="nr", init="auto")
    tables = _write_tables(net)
    figure_path = write_voltage_profile_figure(
        net,
        "outputs/figures/synthetic_feeder_voltage_profile.png",
        title="Synthetic 14-Bus Feeder - Baseline Voltage",
    )
    report_path = Path("outputs/reports/synthetic_feeder_report.json")

    write_powerflow_report(
        report_path,
        metadata=ReportMetadata(
            report_id="synthetic_feeder_report",
            source_domain=PROJECT_NAME,
            project={"name": PROJECT_NAME},
        ),
        net=net,
        inputs=[
            {
                "name": "synthetic_14_bus_radial_feeder",
                "type": "deterministic_project_generator",
            }
        ],
        artifacts=[tables["buses"], tables["lines"], tables["loads"], tables["prosumers"], figure_path],
        summary={"network": "synthetic_14_bus_radial_feeder", "prosumer_count": int(len(PROSUMER_ASSETS))},
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
