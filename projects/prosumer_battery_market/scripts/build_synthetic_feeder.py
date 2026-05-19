"""Build the synthetic feeder, base power-flow report, and prosumer registry."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path("outputs/cache/matplotlib").resolve()))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import pandapower as pp

from gridalyn.assets import prosumer_assets_to_frame
from gridalyn.foundation import ReportMetadata, file_reference, write_report

from network_model import PROSUMER_ASSETS, build_synthetic_feeder


PROJECT_NAME = "prosumer_battery_market"


def _ensure_outputs() -> None:
    for relative in (
        "outputs/data",
        "outputs/figures",
        "outputs/reports",
        "outputs/cache",
    ):
        Path(relative).mkdir(parents=True, exist_ok=True)


def _write_tables(net: pp.pandapowerNet) -> dict[str, Path]:
    bus_path = Path("outputs/data/buses.csv")
    line_path = Path("outputs/data/lines.csv")
    load_path = Path("outputs/data/loads.csv")
    prosumer_path = Path("outputs/data/prosumers.csv")

    net.bus.join(net.res_bus, how="left", rsuffix="_result").to_csv(bus_path, index_label="bus_id")
    net.line.join(net.res_line, how="left", rsuffix="_result").to_csv(line_path, index_label="line_id")
    net.load.join(net.res_load, how="left", rsuffix="_result").to_csv(load_path, index_label="load_id")
    prosumer_assets_to_frame(PROSUMER_ASSETS).to_csv(prosumer_path, index=False)
    return {
        "buses": bus_path,
        "lines": line_path,
        "loads": load_path,
        "prosumers": prosumer_path,
    }


def _write_voltage_figure(net: pp.pandapowerNet) -> Path:
    figure_path = Path("outputs/figures/synthetic_feeder_voltage_profile.png")
    voltage = net.res_bus.vm_pu.reset_index()
    voltage.columns = ["bus_id", "vm_pu"]

    fig, ax = plt.subplots(figsize=(8.5, 4.6))
    ax.plot(voltage["bus_id"], voltage["vm_pu"], marker="o", linewidth=1.8, color="#1f77b4")
    ax.axhline(0.95, color="#c0392b", linestyle="--", linewidth=1.2, label="0.95 p.u.")
    ax.axhline(1.05, color="#7f8c8d", linestyle=":", linewidth=1.2, label="1.05 p.u.")
    ax.set_title("Synthetic 14-Bus Feeder - Baseline Voltage")
    ax.set_xlabel("Bus")
    ax.set_ylabel("Voltage magnitude [p.u.]")
    ax.grid(True, alpha=0.32)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(figure_path, dpi=160)
    plt.close(fig)
    return figure_path


def _summary(net: pp.pandapowerNet) -> dict:
    return {
        "network": "synthetic_14_bus_radial_feeder",
        "bus_count": int(len(net.bus)),
        "line_count": int(len(net.line)),
        "load_count": int(len(net.load)),
        "prosumer_count": int(len(PROSUMER_ASSETS)),
        "slack_count": int(len(net.ext_grid)),
        "converged": bool(net.converged),
        "total_load_mw": float(net.load.p_mw.sum()),
        "total_load_mvar": float(net.load.q_mvar.sum()),
        "total_line_loss_mw": float(net.res_line.pl_mw.sum()),
        "min_voltage_pu": float(net.res_bus.vm_pu.min()),
        "max_voltage_pu": float(net.res_bus.vm_pu.max()),
        "max_line_loading_percent": float(net.res_line.loading_percent.max()),
    }


def main() -> int:
    _ensure_outputs()
    net = build_synthetic_feeder()
    pp.runpp(net, algorithm="nr", init="auto")
    tables = _write_tables(net)
    figure_path = _write_voltage_figure(net)
    report_path = Path("outputs/reports/synthetic_feeder_report.json")

    write_report(
        report_path,
        metadata=ReportMetadata(
            report_id="synthetic_feeder_report",
            source_domain=PROJECT_NAME,
            project={"name": PROJECT_NAME},
        ),
        inputs=[
            {
                "name": "synthetic_14_bus_radial_feeder",
                "type": "deterministic_project_generator",
            }
        ],
        artifacts=[
            file_reference(tables["buses"]),
            file_reference(tables["lines"]),
            file_reference(tables["loads"]),
            file_reference(tables["prosumers"]),
            file_reference(figure_path),
        ],
        summary=_summary(net),
        validation={
            "valid": bool(net.converged),
            "errors": [] if net.converged else ["baseline synthetic feeder power flow did not converge"],
            "warnings": [],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
