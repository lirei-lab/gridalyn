#!/usr/bin/env python3
"""Train the first physics-backed network impact surrogate from pandapower labels."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]

from gridalyn.simulation.analytics.network_impact.physics_model import (
    build_physics_surrogate_report,
    fit_physics_surrogate,
    predict_physics_impact,
    write_physics_surrogate_artifacts,
)


DEFAULT_TRAINING = ROOT / "instances" / "default" / "digital_twin" / "flexibility" / "network_impact_training.parquet"
DEFAULT_LABELS = ROOT / "instances" / "default" / "digital_twin" / "flexibility" / "network_impact_physics_labels.parquet"
DEFAULT_OUT_DIR = ROOT / "instances" / "default" / "digital_twin" / "flexibility"


def _relpath(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario-id", default="S4")
    parser.add_argument("--training-path", type=Path, default=DEFAULT_TRAINING)
    parser.add_argument("--labels-path", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    training = pd.read_parquet(args.training_path)
    labels = pd.read_parquet(args.labels_path)
    training = training.loc[training["scenario_id"] == args.scenario_id].copy()
    labels = labels.loc[labels["scenario_id"] == args.scenario_id].copy()

    model = fit_physics_surrogate(training, labels)
    predictions = predict_physics_impact(training, model)
    report = build_physics_surrogate_report(model, predictions, scenario_id=args.scenario_id)
    report["inputs"] = {
        "training": _relpath(args.training_path),
        "physics_labels": _relpath(args.labels_path),
    }
    paths = write_physics_surrogate_artifacts(
        args.out_dir,
        predictions=predictions,
        report=report,
    )

    print(
        json.dumps(
            {
                "scenario_id": args.scenario_id,
                "summary": report["summary"],
                "paths": {name: _relpath(path) for name, path in paths.items()},
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
