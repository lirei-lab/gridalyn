"""Write the street layer a footprint layer's network build will declare.

A build that fetches streets from OpenStreetMap at run time is not reproducible:
the map changes. Run this once, commit the GeoJSON next to the footprints with
its OpenStreetMap attribution, and declare it in the grid config as
``topology.street_layer = {"path": ..., "sha256": ...}`` using the digest
printed here (bd 4os.7). Needs the ``geo`` extra and network access.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    """Fetch, write and report the street snapshot for a footprint file."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--footprints", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--padding-deg", type=float, default=None)
    parser.add_argument("--network-type", default=None)
    args = parser.parse_args()

    import geopandas as gpd

    from gridalyn.twin.geoprocess.streets import (
        BLOCK_BBOX_PADDING_DEG,
        DEFAULT_NETWORK_TYPE,
        write_street_snapshot,
    )

    bounds = gpd.read_file(args.footprints).total_bounds
    network_type = args.network_type or DEFAULT_NETWORK_TYPE
    padding = BLOCK_BBOX_PADDING_DEG if args.padding_deg is None else args.padding_deg
    digest = write_street_snapshot(
        bounds, args.out, network_type=network_type, padding_deg=padding
    )
    segments = len(gpd.read_file(args.out))
    print(
        json.dumps(
            {
                "path": str(args.out),
                "sha256": digest,
                "segments": segments,
                "network_type": network_type,
                "padding_deg": padding,
                "bounds": [float(value) for value in bounds],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
