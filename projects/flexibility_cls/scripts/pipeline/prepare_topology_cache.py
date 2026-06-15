"""Prepare project-owned synthetic topology cache artifacts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parents[4]
sys.path.insert(0, str(ROOT))

from gridalyn.foundation.data.datasets import get_dataset_path
from gridalyn.simulation.simulators.powerflow.topology_cache import (
    prepare_synthetic_topology_cache,
)
from projects.flexibility_cls.scripts.config import (
    GRID_CONFIG,
    PROJECT_CACHE_DIR,
    TOPOLOGY_CACHE_MANIFEST,
)


def prepare_topology_cache(
    *,
    cache_dir: Path = PROJECT_CACHE_DIR,
    input_file: Path | None = None,
    force_rebuild: bool = False,
) -> Path:
    """Build or refresh the EV project topology cache."""

    source = input_file or get_dataset_path("buildings_inside_polygon.geojson")
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
            "Project-owned runtime cache for the Flexibility CLS workflow.",
            "Generated artifacts under projects/*/outputs are not committed.",
        ],
    )


def main() -> None:
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
