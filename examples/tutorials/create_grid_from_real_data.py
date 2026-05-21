"""Build a synthetic feeder from the bundled footprint sample."""

from __future__ import annotations

from pathlib import Path

from gridalyn.interfaces.cli.environment import configure_cli_environment

configure_cli_environment()

from gridalyn import simulation
from gridalyn.foundation.data import datasets


OUTPUT_DIR = Path("examples/generated/outputs/create_grid_from_real_data")


def main() -> None:
    result = simulation.build_synthetic_network_from_geojson(
        footprints_path=datasets.get_dataset_path("buildings_inside_polygon.geojson"),
        config_path=Path("configs/grid/config.json"),
        out_dir=OUTPUT_DIR,
        write_cache=True,
        run_powerflow=True,
    )

    counts = result.validation_report["counts"]
    print(
        "Bundled-footprint feeder built: "
        f"{counts['buildings']} buildings, "
        f"{counts['pandapower_loads']} loads, "
        f"{counts['pandapower_transformers']} transformers."
    )
    print(f"Validation report: {result.report_path}")


if __name__ == "__main__":
    main()
