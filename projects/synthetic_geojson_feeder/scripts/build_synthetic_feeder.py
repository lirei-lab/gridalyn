"""Build a synthetic distribution feeder from generated GeoJSON footprints."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", str(Path("outputs/cache/matplotlib").resolve()))

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd

from gridalyn.foundation import ReportMetadata, file_reference, write_report
from gridalyn.modeling.synthetic_network import build_synthetic_network_from_geojson


PROJECT_NAME = "synthetic_geojson_feeder"


def _ensure_outputs() -> None:
    for relative in ("outputs/data", "outputs/figures", "outputs/reports", "outputs/cache"):
        Path(relative).mkdir(parents=True, exist_ok=True)


def _write_tables(result) -> dict[str, Path]:
    net = result.net
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


def _bus_positions(net) -> pd.DataFrame:
    if hasattr(net, "bus_geodata") and not net.bus_geodata.empty:
        geodata = net.bus_geodata.copy().reset_index()
        geodata = geodata.rename(columns={geodata.columns[0]: "bus_id"})
        return geodata[["bus_id", "x", "y"]]
    return pd.DataFrame(
        {
            "bus_id": list(net.bus.index),
            "x": [float(index) for index in net.bus.index],
            "y": [0.0 for _ in net.bus.index],
        }
    )


def _write_figure(result) -> Path:
    net = result.net
    figure_path = Path("outputs/figures/synthetic_feeder_topology.png")
    positions = _bus_positions(net).set_index("bus_id")
    fig, ax = plt.subplots(figsize=(7.4, 5.2))
    for line in net.line.itertuples():
        if line.from_bus in positions.index and line.to_bus in positions.index:
            start = positions.loc[line.from_bus]
            end = positions.loc[line.to_bus]
            ax.plot([start.x, end.x], [start.y, end.y], color="#566573", linewidth=1.1)
    ax.scatter(positions["x"], positions["y"], s=18, color="#0aa6b5", label="Buses")
    ax.set_title("Synthetic Feeder From Building GeoJSON")
    ax.set_xlabel("Longitude or projected x")
    ax.set_ylabel("Latitude or projected y")
    ax.grid(True, alpha=0.18)
    ax.legend(loc="best")
    fig.tight_layout()
    fig.savefig(figure_path, dpi=160)
    plt.close(fig)
    return figure_path


def _write_report(result, tables: dict[str, Path], figure_path: Path) -> None:
    net = result.net
    validation = result.validation_report
    summary = {
        "project_intent": "geojson_to_synthetic_feeder",
        "simulation_engine": "pandapower",
        "building_count": int(validation["counts"]["buildings"]),
        "pandapower_bus_count": int(len(net.bus)),
        "pandapower_line_count": int(len(net.line)),
        "pandapower_load_count": int(len(net.load)),
        "pandapower_transformer_count": int(len(net.trafo)),
        "powerflow_converged": bool(validation["powerflow"]["converged"]),
        "min_voltage_pu": float(net.res_bus.vm_pu.min()) if not net.res_bus.empty else None,
        "max_line_loading_pct": (
            float(net.res_line.loading_percent.max()) if not net.res_line.empty else None
        ),
    }
    artifacts = [
        file_reference("outputs/data/building_footprints.geojson"),
        file_reference("outputs/reports/synthetic_network_validation_report.json"),
        *(file_reference(path) for path in tables.values()),
        file_reference(figure_path),
    ]
    write_report(
        "outputs/reports/synthetic_geojson_feeder_report.json",
        metadata=ReportMetadata(
            report_id="synthetic_geojson_feeder_report",
            source_domain="synthetic_network_generation",
            project={"name": PROJECT_NAME},
        ),
        inputs=[
            file_reference("outputs/data/building_footprints.geojson"),
            file_reference("inputs/synthetic_network_config.json"),
        ],
        artifacts=artifacts,
        summary=summary,
        validation={
            "valid": bool(validation["valid"]),
            "errors": [] if validation["valid"] else ["synthetic network validation failed"],
            "warnings": [],
        },
    )


def main() -> int:
    _ensure_outputs()
    result = build_synthetic_network_from_geojson(
        footprints_path="outputs/data/building_footprints.geojson",
        config_path="inputs/synthetic_network_config.json",
        out_dir="outputs/reports",
        clustering_crs="auto",
        write_cache=False,
        run_powerflow=True,
    )
    tables = _write_tables(result)
    figure_path = _write_figure(result)
    _write_report(result, tables, figure_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
