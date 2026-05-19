"""Filter building footprint GeoJSON to a study polygon.

This example is intentionally offline: it can clip building footprints acquired
from OSMnx, Microsoft Global ML Building Footprints after conversion, or any
other GeoJSON source that contains Polygon/MultiPolygon building footprints.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from gridalyn.twin.geoprocess import clip_buildings_by_polygon, load_polygon_coordinates

DEFAULT_BUILDINGS_FILE = "examples/tutorials/data/buildings_tr.json"
DEFAULT_OUTPUT_FILE = "examples/generated/outputs/buildings_inside_polygon.geojson"
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
        description="Clip building footprint GeoJSON to a study polygon."
    )
    parser.add_argument(
        "--buildings-file",
        default=DEFAULT_BUILDINGS_FILE,
        help="Input building footprint GeoJSON.",
    )
    parser.add_argument(
        "--polygon-file",
        default=None,
        help=(
            "Optional JSON/GeoJSON polygon file. Defaults to the "
            "Trois-Rivieres demo polygon."
        ),
    )
    parser.add_argument(
        "--output-file",
        default=DEFAULT_OUTPUT_FILE,
        help="Filtered GeoJSON output path.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    polygon_coords = (
        load_polygon_coordinates(args.polygon_file)
        if args.polygon_file
        else [tuple(coord) for coord in DEFAULT_POLYGON_COORDS]
    )
    clip_buildings_by_polygon(
        buildings_file=Path(args.buildings_file),
        polygon_coordinates=polygon_coords,
        output_file=Path(args.output_file),
    )


if __name__ == "__main__":
    main()
