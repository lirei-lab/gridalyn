"""Run a tiny pandapower feeder and write Gridalyn project artifacts."""

from __future__ import annotations

from pathlib import Path

import pandapower as pp

from gridalyn.assets.modeling import RadialFeederSpec
from gridalyn.foundation import ReportMetadata
from gridalyn.simulation import (
    build_radial_pandapower_feeder,
    write_pandapower_element_tables,
    write_powerflow_report,
    write_voltage_profile_figure,
)


PROJECT_NAME = "minimal_grid_project"


def _build_network() -> pp.pandapowerNet:
    spec = RadialFeederSpec(
        name="minimal_5_bus_radial_feeder",
        bus_count=5,
        sn_mva=2.0,
        base_voltage_kv=12.47,
        slack_vm_pu=1.01,
        loads_mw={1: 0.035, 2: 0.045, 3: 0.03, 4: 0.04},
        q_to_p_ratio=0.25,
        line_length_km=0.25,
        line_r_ohm_per_km=0.28,
        line_x_ohm_per_km=0.18,
        line_c_nf_per_km=5.0,
        line_max_i_ka=0.25,
        bus_y_step=0.15,
    )
    return build_radial_pandapower_feeder(spec)


def main() -> int:
    net = _build_network()
    pp.runpp(net, algorithm="nr", init="auto")
    tables = write_pandapower_element_tables(net, "outputs/data")
    figure_path = write_voltage_profile_figure(
        net,
        "outputs/figures/minimal_voltage_profile.png",
        title="Minimal Feeder Voltage Profile",
        figsize=(7.0, 4.2),
    )
    write_powerflow_report(
        Path("outputs/reports/minimal_grid_report.json"),
        metadata=ReportMetadata(
            report_id="minimal_grid_report",
            source_domain="project_demo",
            project={"name": PROJECT_NAME},
        ),
        net=net,
        artifacts=[*tables.values(), figure_path],
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
