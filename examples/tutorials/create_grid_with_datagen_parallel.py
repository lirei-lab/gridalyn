"""Build the tutorial feeder through the platform synthetic-network API."""

from __future__ import annotations

import argparse
from pathlib import Path

from gridalyn import simulation
from gridalyn.foundation.data import datasets


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default="examples/generated/outputs/datagen_parallel",
        help="Directory for generated tutorial artifacts.",
    )
    args = parser.parse_args(argv)

    result = simulation.build_synthetic_network_from_geojson(
        footprints_path=datasets.get_dataset_path("buildings_inside_polygon.geojson"),
        config_path=Path("configs/grid/config.json"),
        out_dir=Path(args.output_dir),
        write_cache=True,
        run_powerflow=True,
    )

    counts = result.validation_report["counts"]
    print(
        "Tutorial feeder built through Gridalyn: "
        f"{counts['buildings']} buildings, "
        f"{counts['pandapower_buses']} buses."
    )


if __name__ == "__main__":
    main()
