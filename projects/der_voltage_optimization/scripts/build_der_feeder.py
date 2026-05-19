"""Build feeder inputs and the base report for DER voltage optimization."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path("outputs/cache/matplotlib").resolve()))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd
import pandapower as pp

from gridalyn.foundation import ReportMetadata, file_reference, write_report

from network_model import DER_ASSETS, build_der_feeder


PROJECT_NAME = "der_voltage_optimization"


def _ensure_outputs() -> None:
    for relative in ("outputs/data", "outputs/figures", "outputs/reports", "outputs/cache"):
        Path(relative).mkdir(parents=True, exist_ok=True)


def _full_pv_network() -> pp.pandapowerNet:
    net = build_der_feeder()
    for asset in DER_ASSETS:
        pp.create_sgen(
            net,
            bus=int(asset["bus_id"]),
            p_mw=float(asset["pv_available_mw"]),
            q_mvar=0.0,
            name=f"{asset['der_id']}_pv_full",
            type="PV",
        )
    pp.runpp(net, algorithm="nr", init="auto")
    return net


def _write_tables(net: pp.pandapowerNet) -> dict[str, Path]:
    bus_path = Path("outputs/data/buses.csv")
    line_path = Path("outputs/data/lines.csv")
    load_path = Path("outputs/data/loads.csv")
    der_path = Path("outputs/data/der_assets.csv")
    net.bus.join(net.res_bus, how="left", rsuffix="_result").to_csv(bus_path, index_label="bus_id")
    net.line.join(net.res_line, how="left", rsuffix="_result").to_csv(line_path, index_label="line_id")
    net.load.join(net.res_load, how="left", rsuffix="_result").to_csv(load_path, index_label="load_id")
    pd.DataFrame(DER_ASSETS).to_csv(der_path, index=False)
    return {"buses": bus_path, "lines": line_path, "loads": load_path, "der": der_path}


def _write_figure(net: pp.pandapowerNet) -> Path:
    figure_path = Path("outputs/figures/der_feeder_voltage_profile.png")
    voltage = net.res_bus.vm_pu.reset_index()
    voltage.columns = ["bus_id", "vm_pu"]
    fig, ax = plt.subplots(figsize=(8.8, 4.8))
    ax.plot(voltage["bus_id"], voltage["vm_pu"], marker="o", linewidth=1.8)
    ax.axhline(1.05, color="#c0392b", linestyle="--", linewidth=1.2, label="1.05 p.u.")
    ax.axhline(0.95, color="#7f8c8d", linestyle=":", linewidth=1.2, label="0.95 p.u.")
    ax.set_title("DER Feeder - Full PV Voltage Profile")
    ax.set_xlabel("Bus")
    ax.set_ylabel("Voltage magnitude [p.u.]")
    ax.grid(True, alpha=0.32)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(figure_path, dpi=160)
    plt.close(fig)
    return figure_path


def main() -> int:
    _ensure_outputs()
    net = _full_pv_network()
    tables = _write_tables(net)
    figure = _write_figure(net)
    write_report(
        Path("outputs/reports/der_feeder_report.json"),
        metadata=ReportMetadata(
            report_id="der_feeder_report",
            source_domain=PROJECT_NAME,
            project={"name": PROJECT_NAME},
        ),
        inputs=[{"name": "synthetic_16_bus_der_feeder", "type": "deterministic_project_generator"}],
        artifacts=[file_reference(path) for path in (*tables.values(), figure)],
        summary={
            "network": "synthetic_16_bus_der_feeder",
            "bus_count": int(len(net.bus)),
            "line_count": int(len(net.line)),
            "load_count": int(len(net.load)),
            "der_count": int(len(DER_ASSETS)),
            "converged": bool(net.converged),
            "full_pv_mw": float(sum(asset["pv_available_mw"] for asset in DER_ASSETS)),
            "max_voltage_full_pv_pu": float(net.res_bus.vm_pu.max()),
            "min_voltage_full_pv_pu": float(net.res_bus.vm_pu.min()),
            "max_line_loading_full_pv_percent": float(net.res_line.loading_percent.max()),
        },
        validation={
            "valid": bool(net.converged),
            "errors": [] if net.converged else ["full PV feeder power flow did not converge"],
            "warnings": [],
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
