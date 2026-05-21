"""Build a synthetic distribution feeder from generated GeoJSON footprints."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from gridalyn.foundation import ReportMetadata, file_reference, write_report
from gridalyn.simulation import (
    build_pandapower_summary,
    configure_headless_matplotlib,
    write_pandapower_element_tables,
)
from gridalyn.simulation.simulators.powerflow.synthetic_network import build_synthetic_network_from_geojson


PROJECT_NAME = "synthetic_geojson_feeder"


def _write_tables(result) -> dict[str, Path]:
    return write_pandapower_element_tables(result.net, "outputs/data")


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
    configure_headless_matplotlib()
    import matplotlib.pyplot as plt

    net = result.net
    figure_path = Path("outputs/figures/synthetic_feeder_topology.png")
    figure_path.parent.mkdir(parents=True, exist_ok=True)
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
    summary = build_pandapower_summary(
        net,
        extra={
            "project_intent": "geojson_to_synthetic_feeder",
            "building_count": int(validation["counts"]["buildings"]),
            "pandapower_bus_count": int(len(net.bus)),
            "pandapower_line_count": int(len(net.line)),
            "pandapower_load_count": int(len(net.load)),
            "pandapower_transformer_count": int(len(net.trafo)),
            "powerflow_converged": bool(validation["powerflow"]["converged"]),
            "max_line_loading_pct": (
                float(net.res_line.loading_percent.max())
                if not net.res_line.empty
                else None
            ),
        },
    )
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
