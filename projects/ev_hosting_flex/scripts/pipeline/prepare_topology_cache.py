"""Prepare project-owned synthetic topology cache artifacts for ev_hosting_flex."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.simulation import prepare_synthetic_topology_cache
from projects.ev_hosting_flex.scripts.config import (
    GRID_CONFIG,
    PROJECT_CACHE_DIR,
    PROJECT_ROOT,
    TOPOLOGY_CACHE_MANIFEST,
)


def prepare_topology_cache(
    *,
    cache_dir: Path = PROJECT_CACHE_DIR,
    input_file: Path | None = None,
    force_rebuild: bool = False,
) -> Path:
    """Build or refresh the EV hosting-flex project topology cache.

    Builds the synthetic radial twin and pandapower net through the PUBLIC
    ``gridalyn.simulation`` facade only (GUARD-01) and writes the 3 cache files
    plus the footprint-validation report and lineage manifest.

    Args:
        cache_dir: Directory the cache artifacts are written to.
        input_file: Building-footprint GeoJSON. Defaults to the project-local
            copy under ``inputs/buildings.geojson`` (D-03), not the shared SDK
            dataset.
        force_rebuild: Rebuild even when a valid cache already exists.

    Returns:
        The path to the written ``topology_cache_manifest.json``.
    """

    source = input_file or (PROJECT_ROOT / "inputs" / "buildings.geojson")
    manifest_path = (
        TOPOLOGY_CACHE_MANIFEST
        if cache_dir == PROJECT_CACHE_DIR
        else cache_dir / "topology_cache_manifest.json"
    )
    return prepare_synthetic_topology_cache(
        input_file=source,
        cache_dir=cache_dir,
        config=GRID_CONFIG,
        manifest_path=manifest_path,
        force_rebuild=force_rebuild,
        notes=[
            "Project-owned runtime cache for the EV Hosting Flex workflow.",
            "Generated artifacts under projects/*/outputs are not committed.",
        ],
    )


def main() -> None:
    """CLI entry point for the topology-cache stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=PROJECT_CACHE_DIR)
    parser.add_argument("--input-file", type=Path)
    parser.add_argument("--force-rebuild", action="store_true")
    args = parser.parse_args()

    manifest_path = prepare_topology_cache(
        cache_dir=args.cache_dir,
        input_file=args.input_file,
        force_rebuild=args.force_rebuild,
    )
    print(f"Prepared topology cache manifest: {manifest_path}")


if __name__ == "__main__":
    main()
