"""Generate pyCity-style building model artifacts for the digital twin."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]

from gridalyn.assets.modeling import load_base_inputs, write_building_model_artifacts
from gridalyn.assets.modeling.archetypes import NORTH_AMERICA_RESIDENTIAL_PROFILE


DEFAULT_BASE_DIR = ROOT / "digital_twin" / "base"
DEFAULT_OUT_DIR = ROOT / "digital_twin" / "models"


def generate_building_models(
    *,
    base_dir: Path = DEFAULT_BASE_DIR,
    out_dir: Path = DEFAULT_OUT_DIR,
    profile: str = NORTH_AMERICA_RESIDENTIAL_PROFILE,
) -> dict[str, object]:
    buildings, connectivity = load_base_inputs(base_dir)
    return write_building_model_artifacts(
        buildings,
        connectivity,
        out_dir=out_dir,
        root=ROOT,
        profile=profile,
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--profile", default=NORTH_AMERICA_RESIDENTIAL_PROFILE)
    args = parser.parse_args(argv)

    manifest = generate_building_models(
        base_dir=args.base_dir,
        out_dir=args.out_dir,
        profile=args.profile,
    )
    print(json.dumps({"manifest": manifest["manifest_path"], "counts": manifest["counts"]}, indent=2))


if __name__ == "__main__":
    main()
