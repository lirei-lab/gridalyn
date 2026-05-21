"""Build a small synthetic feeder from generated building footprints."""

from __future__ import annotations

import json
from pathlib import Path

from gridalyn import simulation
from gridalyn.twin.adapters import FakeGeoJSONGenerator


OUTPUT_DIR = Path("examples/generated/outputs/basic_grid_creation")


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

    counts = result.validation_report["counts"]
    print(
        "Synthetic feeder built: "
        f"{counts['buildings']} buildings, "
        f"{counts['pandapower_buses']} buses, "
        f"{counts['pandapower_lines']} lines."
    )
    print(f"Validation report: {result.report_path}")


if __name__ == "__main__":
    main()
