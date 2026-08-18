"""Generate scenario-specific building model device overlays."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]

from gridalyn.foundation import layout_from_environment  # noqa: E402

DEFAULT_LAYOUT = layout_from_environment(default_root=ROOT)

from gridalyn.assets.modeling import write_scenario_model_artifacts  # noqa: E402

DEFAULT_MODELS_DIR = DEFAULT_LAYOUT.models
DEFAULT_SCENARIO_DIR = DEFAULT_LAYOUT.scenarios
DEFAULT_OUT_DIR = DEFAULT_MODELS_DIR / "scenarios"


def generate_scenario_models(
    *,
    models_dir: Path = DEFAULT_MODELS_DIR,
    scenario_dir: Path = DEFAULT_SCENARIO_DIR,
    out_dir: Path = DEFAULT_OUT_DIR,
    scenario_id: str | None = None,
) -> dict[str, object]:
    building_models = pd.read_parquet(models_dir / "building_models.parquet")
    base_devices = pd.read_parquet(models_dir / "device_registry.parquet")
    asset_registry = pd.read_parquet(scenario_dir / "asset_registry.parquet")
    return write_scenario_model_artifacts(
        building_models,
        base_devices,
        asset_registry,
        out_dir=out_dir,
        root=ROOT,
        scenario_id=scenario_id,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS_DIR)
    parser.add_argument("--scenario-dir", type=Path, default=DEFAULT_SCENARIO_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scenario-id")
    args = parser.parse_args(argv)

    manifest = generate_scenario_models(
        models_dir=args.models_dir,
        scenario_dir=args.scenario_dir,
        out_dir=args.out_dir,
        scenario_id=args.scenario_id,
    )
    print(
        json.dumps(
            {"manifest": manifest["manifest_path"], "counts": manifest["counts"]},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
