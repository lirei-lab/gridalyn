"""Build reports and figures for the IEEE 33-bus demo project."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path("outputs/cache/matplotlib").resolve()))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import pandapower as pp
import pandapower.networks as pn

from gridalyn.foundation import ReportMetadata, file_reference, write_report


PROJECT_NAME = "ieee_33_bus_demo"


def _ensure_outputs() -> None:
    for relative in (
        "outputs/data",
        "outputs/figures",
        "outputs/reports",
        "outputs/cache",
    ):
        Path(relative).mkdir(parents=True, exist_ok=True)


def _build_network() -> pp.pandapowerNet:
    net = pn.case33bw()
    pp.runpp(net, algorithm="nr", init="auto")
    return net


def _write_tables(net: pp.pandapowerNet) -> dict[str, Path]:
    bus_path = Path("outputs/data/buses.csv")
    line_path = Path("outputs/data/lines.csv")
    load_path = Path("outputs/data/loads.csv")

    buses = net.bus.join(net.res_bus, how="left", rsuffix="_result")
    lines = net.line.join(net.res_line, how="left", rsuffix="_result")
    loads = net.load.join(net.res_load, how="left", rsuffix="_result")

    buses.to_csv(bus_path, index_label="bus_id")
    lines.to_csv(line_path, index_label="line_id")
    loads.to_csv(load_path, index_label="load_id")

    return {
        "buses": bus_path,
        "lines": line_path,
        "loads": load_path,
    }


def _write_voltage_figure(net: pp.pandapowerNet) -> Path:
    figure_path = Path("outputs/figures/ieee33_voltage_profile.png")
    voltage = net.res_bus.vm_pu.reset_index()
    voltage.columns = ["bus_id", "vm_pu"]

    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.plot(voltage["bus_id"], voltage["vm_pu"], marker="o", linewidth=1.8)
    ax.axhline(0.95, color="#c0392b", linestyle="--", linewidth=1.2, label="0.95 p.u.")
    ax.axhline(1.05, color="#7f8c8d", linestyle=":", linewidth=1.2, label="1.05 p.u.")
    ax.set_title("IEEE 33-Bus Demo - Voltage Profile")
    ax.set_xlabel("Bus index")
    ax.set_ylabel("Voltage magnitude [p.u.]")
    ax.grid(True, alpha=0.35)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(figure_path, dpi=160)
    plt.close(fig)
    return figure_path


def _summary(net: pp.pandapowerNet) -> dict:
    total_load_mw = float(net.load.p_mw.sum())
    total_load_mvar = float(net.load.q_mvar.sum())
    total_line_loss_mw = float(net.res_line.pl_mw.sum())
    return {
        "network": "pandapower.networks.case33bw",
        "bus_count": int(len(net.bus)),
        "line_count": int(len(net.line)),
        "load_count": int(len(net.load)),
        "slack_count": int(len(net.ext_grid)),
        "converged": bool(net.converged),
        "total_load_mw": total_load_mw,
        "total_load_mvar": total_load_mvar,
        "total_line_loss_mw": total_line_loss_mw,
        "min_voltage_pu": float(net.res_bus.vm_pu.min()),
        "max_voltage_pu": float(net.res_bus.vm_pu.max()),
        "max_line_loading_percent": float(net.res_line.loading_percent.max()),
    }


def main() -> int:
    _ensure_outputs()
    net = _build_network()
    tables = _write_tables(net)
    figure = _write_voltage_figure(net)
    report_path = Path("outputs/reports/ieee33_powerflow_report.json")

    artifacts = [
        file_reference(path)
        for path in (
            tables["buses"],
            tables["lines"],
            tables["loads"],
            figure,
        )
    ]
    write_report(
        report_path,
        metadata=ReportMetadata(
            report_id="ieee33_powerflow_report",
            source_domain=PROJECT_NAME,
            project={"name": PROJECT_NAME},
        ),
        inputs=[
            {
                "name": "pandapower.networks.case33bw",
                "type": "pandapower_builtin_network",
            }
        ],
        artifacts=artifacts,
        summary=_summary(net),
        validation={
            "valid": bool(net.converged),
            "errors": [] if net.converged else ["pandapower power flow did not converge"],
            "warnings": [],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
