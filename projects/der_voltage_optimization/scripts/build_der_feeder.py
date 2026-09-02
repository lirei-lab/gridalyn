"""Build feeder inputs and the base report for DER voltage optimization."""

from __future__ import annotations

from pathlib import Path

from network_model import DER_ASSETS, build_der_feeder

from gridalyn.assets import der_dispatch_assets_to_frame
from gridalyn.foundation.platform.capabilities import require_capabilities
from gridalyn.projects.scripting import ProjectScript, project_script
from gridalyn.simulation import (
    build_der_dispatch_pandapower_network,
    write_pandapower_element_tables,
    write_powerflow_report,
    write_voltage_profile_figure,
)


def _write_tables(script: ProjectScript, net) -> dict[str, Path]:
    tables = write_pandapower_element_tables(net, script.data_dir)
    der_path = script.data_dir / "der_assets.csv"
    der_dispatch_assets_to_frame(DER_ASSETS).to_csv(der_path, index=False)
    return {**tables, "der": der_path}


def main() -> int:
    script = project_script()
    require_capabilities("sim", context="the DER feeder build")
    der_assets = der_dispatch_assets_to_frame(DER_ASSETS)
    net = build_der_dispatch_pandapower_network(
        build_der_feeder,
        der_assets,
        der_assets["pv_available_mw"].to_numpy(dtype=float),
        der_assets["battery_charge_power_mw"].to_numpy(dtype=float) * 0.0,
    )
    tables = _write_tables(script, net)
    figure = write_voltage_profile_figure(
        net,
        script.figures_dir / "der_feeder_voltage_profile.png",
        title="DER Feeder - Full PV Voltage Profile",
        figsize=(8.8, 4.8),
    )
    write_powerflow_report(
        script.reports_dir / "der_feeder_report.json",
        metadata=script.report_metadata("der_feeder_report"),
        net=net,
        inputs=[
            {
                "name": "synthetic_16_bus_der_feeder",
                "type": "deterministic_project_generator",
            }
        ],
        artifacts=[script.file_reference(path) for path in (*tables.values(), figure)],
        summary={
            "network": "synthetic_16_bus_der_feeder",
            "der_count": int(len(DER_ASSETS)),
            "full_pv_mw": float(der_assets["pv_available_mw"].sum()),
            "max_voltage_full_pv_pu": float(net.res_bus.vm_pu.max()),
            "min_voltage_full_pv_pu": float(net.res_bus.vm_pu.min()),
            "max_line_loading_full_pv_percent": float(
                net.res_line.loading_percent.max()
            ),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
