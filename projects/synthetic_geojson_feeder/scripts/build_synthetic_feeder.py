"""Build a synthetic distribution feeder from generated GeoJSON footprints."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from gridalyn.projects.scripting import ProjectScript, project_script
from gridalyn.simulation import (
    VALIDATION_FILENAME,
    build_pandapower_summary,
    build_synthetic_network_from_geojson,
    write_pandapower_element_tables,
)


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


def _write_figure(script: ProjectScript, result) -> Path:
    import matplotlib.pyplot as plt

    net = result.net
    figure_path = script.figures_dir / "synthetic_feeder_topology.png"
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


def _write_report(
    script: ProjectScript, result, tables: dict[str, Path], figure_path: Path
) -> None:
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
        script.file_reference(script.data_dir / "building_footprints.geojson"),
        script.file_reference(script.data_dir / VALIDATION_FILENAME),
        *(script.file_reference(path) for path in tables.values()),
        script.file_reference(figure_path),
    ]
    script.write_report(
        "synthetic_geojson_feeder_report",
        inputs=[
            script.file_reference(script.data_dir / "building_footprints.geojson"),
            script.file_reference(script.root / "inputs/synthetic_network_config.json"),
            {
                "name": "loadGeneration",
                "type": "generated_load_profile",
                **dict(script.input("loadGeneration")),
            },
        ],
        artifacts=artifacts,
        summary=summary,
        validation={
            "valid": bool(validation["valid"]),
            "errors": (
                [] if validation["valid"] else ["synthetic network validation failed"]
            ),
            "warnings": [],
        },
    )


def _generated_building_peaks_kw(script: ProjectScript) -> list[float]:
    """Per-building peaks from loadGeneration, anchored to the config envelope mean."""
    config = json.loads(
        (script.root / "inputs/synthetic_network_config.json").read_text(
            encoding="utf-8"
        )
    )
    loads = config["loads"]
    anchor_mean_kw = float(loads["max_load_per_building"]) / float(
        loads["diversity_factor_lv"]
    )
    profiles = script.load_generated_load_profiles()
    peaks = profiles.max(axis=0)
    return list(peaks * (anchor_mean_kw / float(peaks.mean())))


def main() -> int:
    script = project_script()
    result = build_synthetic_network_from_geojson(
        footprints_path=script.data_dir / "building_footprints.geojson",
        config_path=script.root / "inputs/synthetic_network_config.json",
        # The build's diagnostic is DATA, not a report: it carries eight
        # domain keys and none of REQUIRED_REPORT_FIELDS, and writing it into
        # outputs/reports/ made it look governed to every reader that classifies
        # by destination. The governed report for this stage is the
        # `script.write_report` call below.
        out_dir=script.data_dir,
        clustering_crs="auto",
        write_cache=False,
        run_powerflow=True,
        building_peak_loads_kw=_generated_building_peaks_kw(script),
    )
    tables = write_pandapower_element_tables(result.net, script.data_dir)
    figure_path = _write_figure(script, result)
    _write_report(script, result, tables, figure_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
