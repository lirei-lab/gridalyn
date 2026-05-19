"""Run a tiny pandapower feeder and write Gridalyn project artifacts."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path("outputs/cache/matplotlib").resolve()))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandapower as pp

from gridalyn.foundation import ReportMetadata, file_reference, write_report


PROJECT_NAME = "minimal_grid_project"


def _ensure_outputs() -> None:
    for relative in ("outputs/data", "outputs/figures", "outputs/reports", "outputs/cache"):
        Path(relative).mkdir(parents=True, exist_ok=True)


def _build_network() -> pp.pandapowerNet:
    net = pp.create_empty_network(sn_mva=2.0)
    for bus_id in range(5):
        pp.create_bus(
            net,
            vn_kv=12.47,
            name=f"bus_{bus_id}",
            geodata=(float(bus_id), 0.15 * float(bus_id % 2)),
        )
    pp.create_ext_grid(net, bus=0, vm_pu=1.01, name="utility_source")
    for from_bus, to_bus in zip(range(4), range(1, 5), strict=True):
        pp.create_line_from_parameters(
            net,
            from_bus=from_bus,
            to_bus=to_bus,
            length_km=0.25,
            r_ohm_per_km=0.28,
            x_ohm_per_km=0.18,
            c_nf_per_km=5.0,
            max_i_ka=0.25,
            name=f"line_{from_bus}_{to_bus}",
        )
    for bus_id, p_mw in {1: 0.035, 2: 0.045, 3: 0.03, 4: 0.04}.items():
        pp.create_load(
            net,
            bus=bus_id,
            p_mw=p_mw,
            q_mvar=p_mw * 0.25,
            name=f"load_bus_{bus_id}",
        )
    return net


def _write_tables(net: pp.pandapowerNet) -> dict[str, Path]:
    buses_path = Path("outputs/data/buses.csv")
    lines_path = Path("outputs/data/lines.csv")
    loads_path = Path("outputs/data/loads.csv")
    net.bus.join(net.res_bus, how="left", rsuffix="_result").to_csv(
        buses_path, index_label="bus_id"
    )
    net.line.join(net.res_line, how="left", rsuffix="_result").to_csv(
        lines_path, index_label="line_id"
    )
    net.load.join(net.res_load, how="left", rsuffix="_result").to_csv(
        loads_path, index_label="load_id"
    )
    return {"buses": buses_path, "lines": lines_path, "loads": loads_path}


def _write_figure(net: pp.pandapowerNet) -> Path:
    figure_path = Path("outputs/figures/minimal_voltage_profile.png")
    voltage = net.res_bus.vm_pu.reset_index()
    voltage.columns = ["bus_id", "vm_pu"]
    fig, ax = plt.subplots(figsize=(7.0, 4.2))
    ax.plot(voltage["bus_id"], voltage["vm_pu"], marker="o", linewidth=1.8)
    ax.axhline(1.05, color="#c0392b", linestyle="--", linewidth=1.0, label="1.05 p.u.")
    ax.axhline(0.95, color="#7f8c8d", linestyle=":", linewidth=1.0, label="0.95 p.u.")
    ax.set_title("Minimal Feeder Voltage Profile")
    ax.set_xlabel("Bus")
    ax.set_ylabel("Voltage [p.u.]")
    ax.grid(True, alpha=0.28)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(figure_path, dpi=160)
    plt.close(fig)
    return figure_path


def _write_report(net: pp.pandapowerNet, tables: dict[str, Path], figure_path: Path) -> None:
    report_path = Path("outputs/reports/minimal_grid_report.json")
    summary = {
        "project_intent": "minimal_grid_hello_world",
        "simulation_engine": "pandapower",
        "bus_count": int(len(net.bus)),
        "line_count": int(len(net.line)),
        "load_count": int(len(net.load)),
        "powerflow_converged": bool(net.converged),
        "min_voltage_pu": float(net.res_bus.vm_pu.min()),
        "max_line_loading_pct": float(net.res_line.loading_percent.max()),
        "total_load_mw": float(net.load.p_mw.sum()),
    }
    write_report(
        report_path,
        metadata=ReportMetadata(
            report_id="minimal_grid_report",
            source_domain="project_demo",
            project={"name": PROJECT_NAME},
        ),
        inputs=[],
        artifacts=[file_reference(path) for path in (*tables.values(), figure_path)],
        summary=summary,
        validation={"valid": bool(net.converged), "errors": [], "warnings": []},
    )


def main() -> int:
    _ensure_outputs()
    net = _build_network()
    pp.runpp(net, algorithm="nr", init="auto")
    tables = _write_tables(net)
    figure_path = _write_figure(net)
    _write_report(net, tables, figure_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
