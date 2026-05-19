"""Generate a scenario asset registry for the digital twin."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]

from gridalyn.assets.modeling.assets import (
    build_asset_registry,
    summarize_asset_registry,
)

DEFAULT_SOFT_PARTICIPATION_RATE = 0.30


DEFAULT_BASE_DIR = ROOT / "instances" / "default" / "digital_twin" / "base"
DEFAULT_SCENARIO_DIR = ROOT / "instances" / "default" / "digital_twin" / "scenarios"
DEFAULT_OUT_PATH = DEFAULT_SCENARIO_DIR / "asset_registry.parquet"
DEFAULT_SUMMARY_PATH = DEFAULT_SCENARIO_DIR / "asset_registry_summary.json"


def generate_asset_registry(
    base_dir: Path,
    scenario_dir: Path,
    out_path: Path,
    summary_path: Path,
    soft_participation_rate: float,
    soft_assignment_seed: int,
    prefer_existing_soft_participants: bool,
) -> pd.DataFrame:
    buildings = pd.read_parquet(base_dir / "buildings.parquet")
    assignments = pd.read_parquet(scenario_dir / "ev_assignments.parquet")
    registry = build_asset_registry(
        buildings,
        assignments,
        soft_participation_rate=soft_participation_rate,
        soft_assignment_seed=soft_assignment_seed,
        prefer_existing_soft_participants=prefer_existing_soft_participants,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    registry.to_parquet(out_path, index=False)

    summary = summarize_asset_registry(registry)
    summary["asset_registry_table"] = str(out_path.relative_to(ROOT))
    summary["soft_participation_rate"] = float(soft_participation_rate)
    summary["soft_assignment_seed"] = int(soft_assignment_seed)
    summary["soft_assignment_source"] = (
        "base_buildings_cls_participant"
        if prefer_existing_soft_participants
        else "seeded_registry_assignment"
    )
    with summary_path.open("w") as f:
        json.dump(summary, f, indent=2, sort_keys=True)

    return registry


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate digital-twin asset registry by scenario."
    )
    parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE_DIR)
    parser.add_argument("--scenario-dir", type=Path, default=DEFAULT_SCENARIO_DIR)
    parser.add_argument("--out-path", type=Path, default=DEFAULT_OUT_PATH)
    parser.add_argument("--summary-path", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument(
        "--soft-participation-rate",
        type=float,
        default=DEFAULT_SOFT_PARTICIPATION_RATE,
    )
    parser.add_argument("--soft-assignment-seed", type=int, default=3042)
    parser.add_argument(
        "--prefer-existing-soft-participants",
        action="store_true",
        help="Use base buildings.cls_participant when it exists and has true values.",
    )
    args = parser.parse_args()

    registry = generate_asset_registry(
        base_dir=args.base_dir,
        scenario_dir=args.scenario_dir,
        out_path=args.out_path,
        summary_path=args.summary_path,
        soft_participation_rate=args.soft_participation_rate,
        soft_assignment_seed=args.soft_assignment_seed,
        prefer_existing_soft_participants=args.prefer_existing_soft_participants,
    )
    scenario_count = registry["scenario_id"].nunique()
    print(
        f"Generated asset registry for {scenario_count} scenarios "
        f"and {len(registry)} scenario-building rows at {args.out_path}"
    )


if __name__ == "__main__":
    main()
