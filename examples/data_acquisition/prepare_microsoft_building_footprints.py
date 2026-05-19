"""Prepare Microsoft Global ML Building Footprints for Gridalyn examples.

Microsoft publishes many partitions as line-delimited GeoJSON inside files with
extensions such as ``.csv.gz``. This script converts a local partition into a
regular GeoJSON FeatureCollection and optionally clips it to a study polygon.
It does not download the Microsoft dataset; keep heavyweight source partitions
outside the repository.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

from gridalyn.twin.geoprocess import prepare_microsoft_building_footprints


def prepare_footprints(
    input_path: Path,
    output_path: Path,
    polygon_path: Path | None = None,
    limit: int | None = None,
) -> int:
    return prepare_microsoft_building_footprints(
        input_path=input_path,
        output_path=output_path,
        polygon_path=polygon_path,
        limit=limit,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Convert a local Microsoft Global ML Building Footprints partition "
            "to clipped GeoJSON."
        )
    )
    parser.add_argument("--input-file", required=True, help="Local Microsoft partition.")
    parser.add_argument("--output-file", required=True, help="GeoJSON output path.")
    parser.add_argument(
        "--polygon-file",
        default=None,
        help="Optional JSON/GeoJSON polygon for clipping.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional maximum number of features to read for smoke tests.",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> None:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    count = prepare_footprints(
        input_path=Path(args.input_file),
        output_path=Path(args.output_file),
        polygon_path=Path(args.polygon_file) if args.polygon_file else None,
        limit=args.limit,
    )
    print(f"Prepared {count} building footprints at {args.output_file}")


if __name__ == "__main__":
    main()
