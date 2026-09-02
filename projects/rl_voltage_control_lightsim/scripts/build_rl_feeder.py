"""Build the RL feeder and baseline report."""

from __future__ import annotations

from pathlib import Path

from network_model import (
    DER_SPEC,
    PV_MAX_MW,
    build_rl_feeder,
    load_multiplier_profile,
    pv_profile,
)

from gridalyn.assets import voltage_control_assets_to_frame
from gridalyn.foundation.platform.capabilities import require_capabilities
from gridalyn.projects.scripting import ProjectScript, project_script
from gridalyn.simulation import (
    LightSimPowerflowAdapter,
    StandardPowerflowScenario,
    run_standard_powerflow_scenario,
    write_pandapower_element_tables,
    write_powerflow_report,
    write_voltage_profile_figure,
)


def _apply_profile(net, step: int) -> None:
    load_multiplier = float(load_multiplier_profile()[step])
    pv_mw = float(PV_MAX_MW * pv_profile()[step])
    base_load_count = len(net.load) - 1
    for load_idx in range(base_load_count):
        net.load.at[load_idx, "p_mw"] *= load_multiplier
        net.load.at[load_idx, "q_mvar"] *= load_multiplier
    net.sgen.at[0, "p_mw"] = pv_mw


def _write_inputs(script: ProjectScript, net) -> dict[str, Path]:
    tables = write_pandapower_element_tables(net, script.data_dir)
    assets_path = script.data_dir / "rl_assets.csv"
    voltage_control_assets_to_frame(DER_SPEC).to_csv(assets_path, index=False)
    return {**tables, "assets": assets_path}


def main() -> int:
    script = project_script()
    require_capabilities("sim", context="the RL feeder build")
    net = build_rl_feeder()
    _apply_profile(net, 11)
    run_standard_powerflow_scenario(
        net,
        StandardPowerflowScenario(
            scenario_id="midday_pv_baseline",
            description="Midday PV operating point for the RL feeder.",
        ),
    )
    lightsim = LightSimPowerflowAdapter(net)
    vm = lightsim.solve_voltage_magnitudes()
    tables = _write_inputs(script, net)
    figure = write_voltage_profile_figure(
        net,
        script.figures_dir / "rl_feeder_voltage_profile.png",
        title="RL Feeder - Midday PV Baseline",
        lower_limit_pu=0.98,
        upper_limit_pu=1.04,
        ylabel="Voltage [p.u.]",
        figsize=(8.5, 4.5),
    )
    write_powerflow_report(
        script.reports_dir / "rl_feeder_report.json",
        metadata=script.report_metadata("rl_feeder_report"),
        net=net,
        inputs=[
            {
                "name": "synthetic_10_bus_rl_feeder",
                "type": "deterministic_project_generator",
            }
        ],
        artifacts=[script.file_reference(path) for path in (*tables.values(), figure)],
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
