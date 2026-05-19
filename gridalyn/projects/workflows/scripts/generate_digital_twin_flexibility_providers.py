"""Generate network-aware flexibility provider artifacts for the digital twin."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]

from gridalyn.foundation import ArtifactLayout

DEFAULT_LAYOUT = ArtifactLayout(ROOT)

from gridalyn.twin.network import NetworkModelRepository
from gridalyn.operations.market.providers import (
    build_network_sensitivity,
    build_provider_registry,
    summarize_provider_registry,
)


DEFAULT_BASE_DIR = DEFAULT_LAYOUT.base
DEFAULT_SCENARIO_DIR = DEFAULT_LAYOUT.scenarios
DEFAULT_MODELS_DIR = DEFAULT_LAYOUT.models
DEFAULT_OUT_DIR = DEFAULT_LAYOUT.flexibility


def _relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def generate_flexibility_provider_artifacts(
    *,
    base_dir: Path,
    scenario_dir: Path,
    models_dir: Path,
    out_dir: Path,
) -> dict:
    asset_registry = pd.read_parquet(scenario_dir / "asset_registry.parquet")
    network_repository = NetworkModelRepository.from_parquet(base_dir)
    validation = network_repository.validate_integrity()
    if not validation.valid:
        raise RuntimeError(
            "Base digital twin network validation failed: "
            + "; ".join(validation.errors[:5])
        )
    connectivity = network_repository.load_model().connectivity
    scenario_model_dir = models_dir / "scenarios"
    scenario_device_paths = sorted(scenario_model_dir.glob("S*_device_registry.parquet"))
    scenario_devices = (
        pd.concat([pd.read_parquet(path) for path in scenario_device_paths], ignore_index=True)
        if scenario_device_paths
        else None
    )

    providers = build_provider_registry(
        asset_registry,
        connectivity,
        scenario_device_registry=scenario_devices,
    )
    sensitivity = build_network_sensitivity(providers)
    summary = summarize_provider_registry(providers)

    out_dir.mkdir(parents=True, exist_ok=True)
    provider_path = out_dir / "provider_registry.parquet"
    sensitivity_path = out_dir / "network_sensitivity.parquet"
    summary_path = out_dir / "provider_registry_summary.json"

    providers.to_parquet(provider_path, index=False)
    sensitivity.to_parquet(sensitivity_path, index=False)

    summary.update(
        {
            "artifacts": {
                "provider_registry": _relpath(provider_path),
                "network_sensitivity": _relpath(sensitivity_path),
            },
            "inputs": {
                "asset_registry": _relpath(scenario_dir / "asset_registry.parquet"),
                "building_grid_connectivity": _relpath(base_dir / "building_grid_connectivity.parquet"),
                "scenario_model_devices": [
                    _relpath(path) for path in scenario_device_paths
                ],
            },
            "n_providers": int(len(providers)),
            "n_sensitivity_rows": int(len(sensitivity)),
        }
    )
    with summary_path.open("w") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate digital-twin flexibility provider registry artifacts."
    )
    parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE_DIR)
    parser.add_argument("--scenario-dir", type=Path, default=DEFAULT_SCENARIO_DIR)
    parser.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    summary = generate_flexibility_provider_artifacts(
        base_dir=args.base_dir,
        scenario_dir=args.scenario_dir,
        models_dir=args.models_dir,
        out_dir=args.out_dir,
    )
    print(
        "Generated flexibility provider registry "
        f"with {summary['n_providers']} providers and "
        f"{summary['n_sensitivity_rows']} sensitivity rows at {args.out_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
