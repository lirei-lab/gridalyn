"""
Export the current grid and building assumptions as an explicit base digital twin.

The exporter materializes four auditable tables:

- buildings.parquet
- grid_buses.parquet
- grid_lines.parquet
- grid_transformers.parquet
- building_grid_connectivity.parquet

It does not change simulation physics and does not use building area as an input
to load generation. Area is exported as metadata only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from gridalyn.foundation import GridalynWorkspace
from gridalyn.twin.adapters.registry import default_network_adapter_registry


ROOT = Path(__file__).resolve().parents[4]
WORKSPACE = GridalynWorkspace(ROOT)
DEFAULT_CACHE_DIR = WORKSPACE.layout.cache
DEFAULT_CONFIG_PATH = ROOT / "configs" / "grid" / "config.json"
DEFAULT_OUT_DIR = WORKSPACE.layout.base


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r") as f:
        return json.load(f)


DEFAULT_ADAPTER_ID = "synthetic_pandapower"


def export_base_twin(
    cache_dir: Path,
    config_path: Path,
    out_dir: Path,
    adapter_id: str = DEFAULT_ADAPTER_ID,
    source_dir: Path | None = None,
) -> None:
    registry = default_network_adapter_registry()
    if source_dir is None:
        adapter = registry.create(adapter_id, cache_dir=cache_dir, config_path=config_path)
    else:
        adapter = registry.create(adapter_id, source_dir=source_dir)
    result = adapter.export(out_dir=out_dir, root=ROOT)
    metadata = _load_json(result.metadata_path)

    print(f"Exported base digital twin to {out_dir}")
    for key, value in metadata["counts"].items():
        print(f"  {key}: {value}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export base grid/building digital twin tables.")
    parser.add_argument("--adapter-id", default=DEFAULT_ADAPTER_ID)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--source-dir",
        type=Path,
        help="Source directory for adapters such as cim_parquet.",
    )
    args = parser.parse_args()

    export_base_twin(
        args.cache_dir,
        args.config,
        args.out_dir,
        adapter_id=args.adapter_id,
        source_dir=args.source_dir,
    )


if __name__ == "__main__":
    main()
