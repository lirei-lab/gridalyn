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
from pathlib import Path

from gridalyn.foundation import workspace_from_environment
from gridalyn.twin.adapters.registry import default_network_adapter_registry

ROOT = Path(__file__).resolve().parents[4]
WORKSPACE = workspace_from_environment(default_root=ROOT)
DEFAULT_CACHE_DIR = WORKSPACE.layout.cache
DEFAULT_CONFIG_PATH = ROOT / "configs" / "grid" / "config.json"
DEFAULT_OUT_DIR = WORKSPACE.layout.base


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
        adapter = registry.create(
            adapter_id, cache_dir=cache_dir, config_path=config_path
        )
    else:
        adapter = registry.create(adapter_id, source_dir=source_dir)
    result = adapter.export(out_dir=out_dir, root=ROOT)

    # `identity` is read back off disk by the export itself, through the same
    # repository read path a consumer uses, so this reports what a reader will
    # actually resolve rather than re-parsing the JSON the writer just produced.
    print(f"Exported base digital twin to {out_dir}")
    print(f"  model: {result.identity.id}")
    print(f"  profile: {result.identity.profile}")
    for key, value in result.counts.items():
        print(f"  {key}: {value}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export base grid/building digital twin tables."
    )
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
