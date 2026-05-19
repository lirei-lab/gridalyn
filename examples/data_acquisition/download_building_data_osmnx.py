"""Download OpenStreetMap building footprints with OSMnx."""

from __future__ import annotations

import argparse
from pathlib import Path

from gridalyn.twin.geoprocess import download_osm_building_footprints, load_polygon_coordinates

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
    parser = argparse.ArgumentParser(
        description="Download OSM building footprints inside a polygon with OSMnx."
    )
    parser.add_argument(
        "--polygon-file",
        default=None,
        help="Optional JSON/GeoJSON polygon file. Defaults to the Trois-Rivieres demo polygon.",
    )
    parser.add_argument(
        "--output-file",
        default="examples/generated/outputs/osmnx_buildings.geojson",
        help="GeoJSON output path.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    polygon_coordinates = (
        load_polygon_coordinates(args.polygon_file)
        if args.polygon_file
        else [tuple(coord) for coord in DEFAULT_POLYGON_COORDS]
    )
    download_osm_building_footprints(polygon_coordinates, Path(args.output_file))
    print(f"Building footprints saved to {args.output_file}")


if __name__ == "__main__":
    main()
