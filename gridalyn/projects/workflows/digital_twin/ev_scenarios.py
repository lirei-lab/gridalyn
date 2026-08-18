"""Generate deterministic EV adoption overlays for the base digital twin."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from gridalyn.assets.datagen.agents import L2_MID_KW
from gridalyn.twin.network import NetworkModelRepository

ROOT = Path(__file__).resolve().parents[4]

from gridalyn.foundation import layout_from_environment  # noqa: E402

DEFAULT_LAYOUT = layout_from_environment(default_root=ROOT)
DEFAULT_BASE_DIR = DEFAULT_LAYOUT.base
DEFAULT_OUT_DIR = DEFAULT_LAYOUT.scenarios
DEFAULT_CONFIG_PATH = ROOT / "configs" / "grid" / "config.json"

SCENARIOS = [
    {"scenario_id": "S0", "ev_penetration_pct": 0},
    {"scenario_id": "S1", "ev_penetration_pct": 10},
    {"scenario_id": "S2", "ev_penetration_pct": 20},
    {"scenario_id": "S3", "ev_penetration_pct": 30},
    {"scenario_id": "S4", "ev_penetration_pct": 40},
]


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r") as f:
        return json.load(f)


def _relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _config_hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(config, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _scenario_ev_count(n_buildings: int, penetration_pct: int) -> int:
    return int(round(n_buildings * penetration_pct / 100.0))


def generate_ev_scenarios(
    base_dir: Path,
    out_dir: Path,
    config_path: Path,
    assignment_seed: int | None,
    charger_kw: float,
    c_soft_fraction: float,
) -> None:
    metadata_path = base_dir / "metadata.json"
    repo = NetworkModelRepository.from_parquet(base_dir)
    validation = repo.validate_integrity()
    if not validation.valid:
        raise RuntimeError(
            "Base digital twin network validation failed: "
            + "; ".join(validation.errors[:5])
        )
    buildings = repo.load_model().buildings
    base_metadata = _load_json(metadata_path)
    config = _load_json(config_path)

    seed = int(
        assignment_seed
        if assignment_seed is not None
        else config.get("simulation", {}).get("seed", 42) + 1000
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    n_buildings = len(buildings)
    if n_buildings == 0:
        raise ValueError(
            f"ev_scenarios: the base twin at {out_dir.parent / 'base'} holds zero "
            "buildings, so every scenario would be generated over an empty set and "
            "would overwrite the existing scenario overlays with n_ev=0. Build the "
            "base first: `gridalyn twin base` (or `gridalyn twin build`), then "
            "re-run this stage."
        )

    rng = np.random.default_rng(seed)
    permutation = rng.permutation(n_buildings)

    assignment_rows = []
    scenario_summaries = []

    stable_buildings = buildings.reset_index(drop=True)
    for scenario in SCENARIOS:
        scenario_id = scenario["scenario_id"]
        penetration_pct = int(scenario["ev_penetration_pct"])
        n_ev = _scenario_ev_count(n_buildings, penetration_pct)
        selected_positions = set(int(pos) for pos in permutation[:n_ev])

        ev_counter = 0
        for pos, row in stable_buildings.iterrows():
            has_ev = int(pos) in selected_positions
            ev_id = f"ev:{scenario_id}:{ev_counter}" if has_ev else None
            if has_ev:
                ev_counter += 1
            assignment_rows.append(
                {
                    "scenario_id": scenario_id,
                    "building_id": row["building_id"],
                    "load_id": row["load_id"],
                    "pandapower_load": int(row["pandapower_load"]),
                    "has_ev": bool(has_ev),
                    "ev_id": ev_id,
                    "charger_kw": float(charger_kw) if has_ev else 0.0,
                    "c_soft_fraction": float(c_soft_fraction) if has_ev else 0.0,
                    "assignment_seed": seed,
                    "ontology_class": "EVChargingAsset" if has_ev else "Building",
                }
            )

        scenario_doc = {
            "scenario_id": scenario_id,
            "ev_penetration_pct": penetration_pct,
            "n_buildings": int(n_buildings),
            "n_ev": int(n_ev),
            "ev_assignment_seed": seed,
            "assignment_policy": "seeded_nested_random_permutation_of_building_id",
            "area_m2_used_for_assignment": False,
            "charger_kw": float(charger_kw),
            "c_soft_fraction": float(c_soft_fraction),
            "cls_mode": "none",
            "base_twin_metadata": _relpath(metadata_path),
            "base_config_hash": base_metadata.get("config_hash"),
            "grid_planning_config_hash": _config_hash(config),
            "assignment_table": _relpath(out_dir / "ev_assignments.parquet"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        scenario_summaries.append(scenario_doc)
        with (out_dir / f"{scenario_id}.json").open("w") as f:
            json.dump(scenario_doc, f, indent=2, sort_keys=True)

    assignments = pd.DataFrame(assignment_rows)
    assignments.to_parquet(out_dir / "ev_assignments.parquet", index=False)

    index_doc = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "assignment_seed": seed,
        "area_m2_used_for_assignment": False,
        "scenarios": scenario_summaries,
    }
    with (out_dir / "index.json").open("w") as f:
        json.dump(index_doc, f, indent=2, sort_keys=True)

    print(f"Generated EV scenario overlays in {out_dir}")
    for summary in scenario_summaries:
        print(
            f"  {summary['scenario_id']}: "
            f"{summary['ev_penetration_pct']}% -> {summary['n_ev']} EVs"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate EV scenario overlays for the digital twin."
    )
    parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--assignment-seed", type=int, default=None)
    parser.add_argument("--charger-kw", type=float, default=L2_MID_KW)
    parser.add_argument("--c-soft-fraction", type=float, default=0.65)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    generate_ev_scenarios(
        base_dir=args.base_dir,
        out_dir=args.out_dir,
        config_path=args.config,
        assignment_seed=args.assignment_seed,
        charger_kw=args.charger_kw,
        c_soft_fraction=args.c_soft_fraction,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
