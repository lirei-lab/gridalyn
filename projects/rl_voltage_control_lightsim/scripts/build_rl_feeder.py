"""Build the RL feeder and baseline report."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path("outputs/cache/matplotlib").resolve()))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandapower as pp

from gridalyn.assets import voltage_control_assets_to_frame
from gridalyn.foundation import ReportMetadata, file_reference, write_report
from gridalyn.simulation import LightSimPowerflowAdapter

from network_model import (
    DER_SPEC,
    PV_MAX_MW,
    build_rl_feeder,
    load_multiplier_profile,
    pv_profile,
)


PROJECT_NAME = "rl_voltage_control_lightsim"


def _ensure_outputs() -> None:
    for relative in ("outputs/data", "outputs/figures", "outputs/reports", "outputs/cache"):
        Path(relative).mkdir(parents=True, exist_ok=True)


def _apply_profile(net: pp.pandapowerNet, step: int) -> None:
    load_multiplier = float(load_multiplier_profile()[step])
    pv_mw = float(PV_MAX_MW * pv_profile()[step])
    base_load_count = len(net.load) - 1
    for load_idx in range(base_load_count):
        net.load.at[load_idx, "p_mw"] *= load_multiplier
        net.load.at[load_idx, "q_mvar"] *= load_multiplier
    net.sgen.at[0, "p_mw"] = pv_mw


def _write_inputs(net: pp.pandapowerNet) -> dict[str, Path]:
    bus_path = Path("outputs/data/buses.csv")
    line_path = Path("outputs/data/lines.csv")
    load_path = Path("outputs/data/loads.csv")
    assets_path = Path("outputs/data/rl_assets.csv")
    net.bus.join(net.res_bus, how="left", rsuffix="_result").to_csv(bus_path, index_label="bus_id")
    net.line.join(net.res_line, how="left", rsuffix="_result").to_csv(line_path, index_label="line_id")
    net.load.join(net.res_load, how="left", rsuffix="_result").to_csv(load_path, index_label="load_id")
    voltage_control_assets_to_frame(DER_SPEC).to_csv(assets_path, index=False)
    return {"buses": bus_path, "lines": line_path, "loads": load_path, "assets": assets_path}


def _write_figure(net: pp.pandapowerNet) -> Path:
    figure_path = Path("outputs/figures/rl_feeder_voltage_profile.png")
    voltage = net.res_bus.vm_pu.reset_index()
    voltage.columns = ["bus_id", "vm_pu"]
    fig, ax = plt.subplots(figsize=(8.5, 4.5))
    ax.plot(voltage["bus_id"], voltage["vm_pu"], marker="o", linewidth=1.8)
    ax.axhline(1.04, color="#c0392b", linestyle="--", linewidth=1.2, label="control upper band")
    ax.axhline(0.98, color="#7f8c8d", linestyle=":", linewidth=1.2, label="control lower band")
    ax.set_title("RL Feeder - Midday PV Baseline")
    ax.set_xlabel("Bus")
    ax.set_ylabel("Voltage [p.u.]")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(figure_path, dpi=160)
    plt.close(fig)
    return figure_path


def main() -> int:
    _ensure_outputs()
    net = build_rl_feeder()
    _apply_profile(net, 11)
    pp.runpp(net, algorithm="nr", init="auto")
    lightsim = LightSimPowerflowAdapter(net)
    vm = lightsim.solve_voltage_magnitudes()
    tables = _write_inputs(net)
    figure = _write_figure(net)
    write_report(
        Path("outputs/reports/rl_feeder_report.json"),
        metadata=ReportMetadata(
            report_id="rl_feeder_report",
            source_domain=PROJECT_NAME,
            project={"name": PROJECT_NAME},
        ),
        inputs=[{"name": "synthetic_10_bus_rl_feeder", "type": "deterministic_project_generator"}],
        artifacts=[file_reference(path) for path in (*tables.values(), figure)],
        summary={
            "network": "synthetic_10_bus_rl_feeder",
            "simulation_engine": "lightsim2grid",
            "modeling_contract": "gridalyn_voltage_control_environment",
            "bus_count": int(len(net.bus)),
            "line_count": int(len(net.line)),
            "load_count": int(len(net.load)),
            "sgen_count": int(len(net.sgen)),
            "converged": bool(net.converged),
            "max_voltage_midday_pu": float(max(vm)),
            "min_voltage_midday_pu": float(min(vm)),
        },
        validation={
            "valid": bool(net.converged),
            "errors": [] if net.converged else ["midday feeder power flow did not converge"],
            "warnings": [],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
