"""Build the RL feeder and baseline report."""

from __future__ import annotations

from pathlib import Path

import pandapower as pp

from gridalyn.assets import voltage_control_assets_to_frame
from gridalyn.foundation import ReportMetadata
from gridalyn.simulation import (
    LightSimPowerflowAdapter,
    write_pandapower_element_tables,
    write_powerflow_report,
    write_voltage_profile_figure,
)

from network_model import (
    DER_SPEC,
    PV_MAX_MW,
    build_rl_feeder,
    load_multiplier_profile,
    pv_profile,
)


PROJECT_NAME = "rl_voltage_control_lightsim"


def _apply_profile(net: pp.pandapowerNet, step: int) -> None:
    load_multiplier = float(load_multiplier_profile()[step])
    pv_mw = float(PV_MAX_MW * pv_profile()[step])
    base_load_count = len(net.load) - 1
    for load_idx in range(base_load_count):
        net.load.at[load_idx, "p_mw"] *= load_multiplier
        net.load.at[load_idx, "q_mvar"] *= load_multiplier
    net.sgen.at[0, "p_mw"] = pv_mw


def _write_inputs(net: pp.pandapowerNet) -> dict[str, Path]:
    tables = write_pandapower_element_tables(net, "outputs/data")
    assets_path = Path("outputs/data/rl_assets.csv")
    assets_path.parent.mkdir(parents=True, exist_ok=True)
    voltage_control_assets_to_frame(DER_SPEC).to_csv(assets_path, index=False)
    return {**tables, "assets": assets_path}


def main() -> int:
    net = build_rl_feeder()
    _apply_profile(net, 11)
    pp.runpp(net, algorithm="nr", init="auto")
    lightsim = LightSimPowerflowAdapter(net)
    vm = lightsim.solve_voltage_magnitudes()
    tables = _write_inputs(net)
    figure = write_voltage_profile_figure(
        net,
        "outputs/figures/rl_feeder_voltage_profile.png",
        title="RL Feeder - Midday PV Baseline",
        lower_limit_pu=0.98,
        upper_limit_pu=1.04,
        ylabel="Voltage [p.u.]",
        figsize=(8.5, 4.5),
    )
    write_powerflow_report(
        Path("outputs/reports/rl_feeder_report.json"),
        metadata=ReportMetadata(
            report_id="rl_feeder_report",
            source_domain=PROJECT_NAME,
            project={"name": PROJECT_NAME},
        ),
        net=net,
        inputs=[{"name": "synthetic_10_bus_rl_feeder", "type": "deterministic_project_generator"}],
        artifacts=[*tables.values(), figure],
        summary={
            "network": "synthetic_10_bus_rl_feeder",
            "simulation_engine": "lightsim2grid",
            "modeling_contract": "gridalyn_voltage_control_environment",
            "max_voltage_midday_pu": float(max(vm)),
            "min_voltage_midday_pu": float(min(vm)),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
