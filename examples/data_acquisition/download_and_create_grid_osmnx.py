"""Download OSM building footprints and build a tutorial grid."""

from __future__ import annotations

import argparse
from pathlib import Path

from gridalyn import simulation
from gridalyn.twin.geoprocess import BuildingDownloader, load_polygon_coordinates


DEFAULT_POLYGON_COORDS = [
    [-72.62417036110914, 46.34726673598499],
    [-72.61452837213456, 46.35379678880483],
    [-72.61013276391213, 46.354794761027705],
    [-72.58624610343783, 46.339943052357285],
    [-72.58659312513969, 46.33910452912204],
    [-72.59730468715948, 46.32824092363754],
    [-72.6237240054993, 46.34619741748094],
    [-72.62417036110914, 46.34726673598499],
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--polygon-file",
        default=None,
        help="Optional JSON/GeoJSON polygon file. Defaults to the Trois-Rivieres demo polygon.",
    )
    parser.add_argument(
        "--output-dir",
        default="examples/generated/outputs/osmnx_grid",
        help="Directory for downloaded footprints and generated artifacts.",
    )
    parser.add_argument(
        "--buildings-output",
        default="osm_buildings.geojson",
        help="Filename for downloaded OSM building footprints.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    polygon_coordinates = (
        load_polygon_coordinates(args.polygon_file)
        if args.polygon_file
        else [tuple(coord) for coord in DEFAULT_POLYGON_COORDS]
    )
    buildings_path = output_dir / args.buildings_output
    BuildingDownloader().download_buildings(
        tuple(tuple(float(c) for c in coord) for coord in polygon_coordinates),
        str(buildings_path),
    )

    result = simulation.build_synthetic_network_from_geojson(
        footprints_path=buildings_path,
        config_path=Path("configs/grid/config.json"),
        out_dir=output_dir,
        write_cache=True,
        run_powerflow=True,
    )
    counts = result.validation_report["counts"]
    print(
        "OSM feeder built: "
        f"{counts['buildings']} buildings, "
        f"{counts['pandapower_buses']} buses."
    )
    print(f"Validation report: {result.report_path}")


if __name__ == "__main__":
    main()
