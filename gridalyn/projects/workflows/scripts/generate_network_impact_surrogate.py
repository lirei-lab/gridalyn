#!/usr/bin/env python3
"""Generate GNN-ready network impact surrogate artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]

from gridalyn.simulation.analytics.network_impact.surrogate import (
    build_edge_features,
    build_graph_snapshot,
    build_node_features,
    build_provider_impact_predictions,
    build_surrogate_report,
    build_training_dataset,
    write_surrogate_artifacts,
)


DEFAULT_PROVIDER_REGISTRY = ROOT / "digital_twin" / "flexibility" / "provider_registry.parquet"
DEFAULT_SENSITIVITY = ROOT / "digital_twin" / "flexibility" / "network_sensitivity.parquet"
DEFAULT_OUT_DIR = ROOT / "digital_twin" / "flexibility"


def _relpath(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario-id", default="S4")
    parser.add_argument("--provider-registry", type=Path, default=DEFAULT_PROVIDER_REGISTRY)
    parser.add_argument("--sensitivity", type=Path, default=DEFAULT_SENSITIVITY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    providers = pd.read_parquet(args.provider_registry)
    sensitivity = pd.read_parquet(args.sensitivity)

    nodes, edges = build_graph_snapshot(providers, sensitivity, scenario_id=args.scenario_id)
    node_features = build_node_features(nodes)
    edge_features = build_edge_features(edges)
    training = build_training_dataset(providers, sensitivity, scenario_id=args.scenario_id)
    predictions = build_provider_impact_predictions(training)
    report = build_surrogate_report(
        nodes,
        edges,
        training,
        predictions,
        scenario_id=args.scenario_id,
    )
    paths = write_surrogate_artifacts(
        args.out_dir,
        nodes=nodes,
        edges=edges,
        node_features=node_features,
        edge_features=edge_features,
        training=training,
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
