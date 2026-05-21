"""Generate a synthetic feeder and render a lightweight network map."""

from __future__ import annotations

import json
from pathlib import Path

from gridalyn import interfaces, simulation
from gridalyn.twin.adapters import FakeGeoJSONGenerator


OUTPUT_DIR = Path("examples/generated/outputs/generate_and_visualize_grid")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    footprints_path = OUTPUT_DIR / "generated_buildings.geojson"
    footprints_path.write_text(
        json.dumps(FakeGeoJSONGenerator(grid_size=8).generate_geojson()),
        encoding="utf-8",
    )

    result = simulation.build_synthetic_network_from_geojson(
        footprints_path=footprints_path,
        config_path=Path("configs/grid/config.json"),
        out_dir=OUTPUT_DIR,
        write_cache=True,
        run_powerflow=True,
    )

    map_path = OUTPUT_DIR / "grid_layers.html"
    interfaces.GridPlotter(result.power_grid).plot_building_and_centroid_graph(
        plot_lv_edges=True,
        plot_mv_edges=True,
        plot_hv_edges=True,
    ).save(map_path)

    print(f"Validation report: {result.report_path}")
    print(f"Map: {map_path}")


if __name__ == "__main__":
    main()
