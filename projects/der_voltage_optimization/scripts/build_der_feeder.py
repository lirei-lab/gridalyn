"""Build feeder inputs and the base report for DER voltage optimization."""

from __future__ import annotations

from pathlib import Path

from gridalyn.assets import der_dispatch_assets_to_frame
from gridalyn.foundation import ReportMetadata
from gridalyn.simulation import (
    build_der_dispatch_pandapower_network,
    write_pandapower_element_tables,
    write_powerflow_report,
    write_voltage_profile_figure,
)

from network_model import DER_ASSETS, build_der_feeder


PROJECT_NAME = "der_voltage_optimization"


def _write_tables(net) -> dict[str, Path]:
    tables = write_pandapower_element_tables(net, "outputs/data")
    der_path = Path("outputs/data/der_assets.csv")
    der_path.parent.mkdir(parents=True, exist_ok=True)
    der_dispatch_assets_to_frame(DER_ASSETS).to_csv(der_path, index=False)
    return {**tables, "der": der_path}


def main() -> int:
    der_assets = der_dispatch_assets_to_frame(DER_ASSETS)
    net = build_der_dispatch_pandapower_network(
        build_der_feeder,
        der_assets,
        der_assets["pv_available_mw"].to_numpy(dtype=float),
        der_assets["battery_charge_power_mw"].to_numpy(dtype=float) * 0.0,
    )
    tables = _write_tables(net)
    figure = write_voltage_profile_figure(
        net,
        "outputs/figures/der_feeder_voltage_profile.png",
        title="DER Feeder - Full PV Voltage Profile",
        figsize=(8.8, 4.8),
    )
    write_powerflow_report(
        Path("outputs/reports/der_feeder_report.json"),
        metadata=ReportMetadata(
            report_id="der_feeder_report",
            source_domain=PROJECT_NAME,
            project={"name": PROJECT_NAME},
        ),
        net=net,
        inputs=[{"name": "synthetic_16_bus_der_feeder", "type": "deterministic_project_generator"}],
        artifacts=[*tables.values(), figure],
        summary={
            "network": "synthetic_16_bus_der_feeder",
            "der_count": int(len(DER_ASSETS)),
            "full_pv_mw": float(der_assets["pv_available_mw"].sum()),
            "max_voltage_full_pv_pu": float(net.res_bus.vm_pu.max()),
            "min_voltage_full_pv_pu": float(net.res_bus.vm_pu.min()),
            "max_line_loading_full_pv_percent": float(net.res_line.loading_percent.max()),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
